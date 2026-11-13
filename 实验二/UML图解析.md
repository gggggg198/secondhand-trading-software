# 小蓝鲸二手集市 UML 图解析

项目为**小蓝鲸二手集市**，面向校园单件二手交易。设计基于[实验一的 32 条需求](../实验一/requirements.md)、十项人工审查意见及后续收藏反馈。商品经审核发布，买家独占预约，双方线下交付。事务规则为后端实现契约，真实 PostgreSQL 与 HTTP 接口验收在实现阶段进行。

设计采用模块化单体和一个 PostgreSQL 数据库。商品交易服务统一办理商品、预约和审核状态变更。九张图覆盖四种 UML 类型，包括三张类图、一张组件图、两张状态图及三张时序图。收藏与应用记录各有独立类图，便于查阅核心交易。

| 图 | 图片 | 可编辑源文件 | 主要解释 |
|---|---|---|---|
| 核心领域类图 | [PNG](UML/UML类图.png) | [PlantUML](UML/UML类图.puml) | 核心对象、所有权、快照、业务接口 |
| 应用与记录类图 | [PNG](UML/UML类图_应用与记录.png) | [PlantUML](UML/UML类图_应用与记录.puml) | 事务编排、幂等结果、审计职责 |
| 商品收藏类图 | [PNG](UML/UML类图_商品收藏.png) | [PlantUML](UML/UML类图_商品收藏.puml) | 账号与商品的唯一收藏关系、关注量 |
| 组件图 | [PNG](UML/UML组件图.png) | [PlantUML](UML/UML组件图.puml) | 谁调用谁、统一写入口、事务位置 |
| 商品状态图 | [PNG](UML/UML状态图_商品.png) | [PlantUML](UML/UML状态图_商品.puml) | 八种商品状态与对应方法 |
| 预约状态图 | [PNG](UML/UML状态图_预约.png) | [PlantUML](UML/UML状态图_预约.puml) | 六种预约状态及商品联动 |
| 正常预约时序图 | [PNG](UML/UML时序图_正常预约.png) | [PlantUML](UML/UML时序图_正常预约.puml) | 一个成功预约的提交边界 |
| 并发竞争时序图 | [PNG](UML/UML时序图_并发竞争.png) | [PlantUML](UML/UML时序图_并发竞争.puml) | 两名买家与卖家下架的三方竞争 |
| 幂等重试时序图 | [PNG](UML/UML时序图_幂等重试.png) | [PlantUML](UML/UML时序图_幂等重试.puml) | 等待、回滚重试、已提交结果恢复 |

## 1. 所有图共同遵守的契约

设 `A(p)` 是商品 p 的所有“待卖家确认或卖家已确认”预约，`C(p)` 是商品 p 的所有“已完成”预约。有效性由预约状态决定。即使截止时间已经到达，在合法过期事务提交前，待确认记录仍占用商品，但不能再被卖家接受。

| 编号 | 每次成功提交后的不变量 | 落实方式 |
|---|---|---|
| I1 独占 | `count(A(p)) <= 1` | 按商品的有效预约条件唯一索引；所有相关写操作先锁同一商品行 |
| I2 状态一致 | `p.status = 已预约 ⇔ count(A(p)) = 1`；其他商品状态均没有有效预约 | Product 同步改变两个对象，事务 T 共同保存；提交前检查 |
| I3 成交一致 | `p.status = 已售出 ⇔ count(C(p)) = 1`，且 `count(A(p)) = 0`；其他状态没有已完成预约 | 完成方法同时更新；已完成预约条件唯一索引；已售出不再发布 |
| I4 当事人 | `r.seller = r.product.seller`，`r.buyer != r.product.seller`；商品卖家和预约所属商品不可改变 | 预约卖家为派生角色；创建时检查非自购；外键保证关联存在 |
| I5 历史 | 终态不复活；原价、交付约定和创建时间不可改；首次完成时间只写一次 | 无任意修改历史的接口；重试不调用领域方法 |
| I6 原子结果 | 一次成功变更对应的业务、最终操作结果、成功变更审计共同提交或回滚 | 同连接、同事务；SUCCESS 结果不另开事务补写 |
| I7 页面依据 | 新命令匹配当前 `version`；每次商品、预约或审核相关实际变更递增一次 | 商品为统一版本边界；重试、业务拒绝和无效旧任务不递增 |

“当前预约”就是 `A(p)` 中唯一的元素，即 `/activeReservation`，没有另一个独立维护的 `activeReservationID`。处理旧预约 r 时须确认它属于 p、仍有效、且 `r = /activeReservation`。旧取消或旧到期任务无法结束后来预约。

商品状态包含审核、下架、封禁等信息，不能全部由预约状态推导，所以保留两个对象各自的状态。消除的是多余的当前占用指针。

数据库使用主键、外键、枚举/取值检查和以下索引。物理字段采用 `snake_case` 的 `id`，类图采用 `ID`。

```sql
CREATE UNIQUE INDEX uq_active_reservation ON reservation(product_id)
WHERE status IN ('PENDING', 'CONFIRMED');
CREATE UNIQUE INDEX uq_completed_reservation ON reservation(product_id)
WHERE status = 'COMPLETED';
CREATE UNIQUE INDEX uq_pending_review ON review_submission(product_id)
WHERE status = 'PENDING';
-- 下面三个字段均为 NOT NULL
CREATE UNIQUE INDEX uq_operation_key
ON operation_result(actor_ref, action, submission_key);
```

这些是存储设计片段，未在本机数据库执行。条件唯一索引约束数量，**不会自动证明商品与预约的跨表状态等价关系**。I2、I3 依赖统一写入口、商品锁、Product 方法和共同事务。本设计不引入额外触发器；绕过应用入口手工改库不在该保证范围内。普通 PostgreSQL `CHECK` 不能承担跨表不变量。[官方约束说明](https://www.postgresql.org/docs/17/ddl-constraints.html)

## 2. 核心领域类图：对象、关联和必要快照

类框上部为属性，下部为方法；`1` 表示一个，`0..*` 表示可保留多条，`0..5` 表示最多五张图片。`+` 为业务入口，`~` 为领域包内协作，`/` 为派生信息。关联已经表达卖家、买家、商品和历史记录，在数据库中映射为外键，不在同一领域图重复列一套外键属性。

**Account。** 账号可在不同交易中充当买家或卖家，不建立 Buyer、Seller 子类。`username` 保留显示形式，`/normalizedUsername` 为忽略大小写的唯一性键，用表达式唯一索引或生成列实现，不能独立编辑。密码保存哈希，管理员为权限标记。注册、会话和授撤权由账号模块办理；并发撤权不能清空管理员的 REQ-003 仍需实现。

**Product。** 商品是商品/预约/审核状态联动的入口，具有一个不可变 seller，多次审核提交和历史预约。没有公开的任意 `setStatus()`。应用服务在商品锁内调用业务方法并共同保存。`content : ProductContent` 包括标题、描述、分类、成色和价格；当前图片仅由 images 关联表达，不重复放进 content。草稿可不完整，送审时连同图片按 REQ-005 完整校验。

`version` 是整个商品业务的唯一并发版本。接受预约虽不改变商品的“已预约”状态，也改变了关联预约，仍要递增 version。删除独立的预约版本；预约详情返回所属商品的 version，供下一次新动作使用。

`/currentReview` 从仍处于待审状态的提交推导；同商品最多一条待审提交，而且商品待审核当且仅当存在这条待审提交。撤回、审核和平台封禁都在同一事务结束相应待审提交，旧 submissionID 无法作用于后来提交。没有单独的 currentReviewID 指针。

**Reservation。** 预约保存买家、所属商品、原价与交付约定。卖家由 `r.product.seller` 确定。本期没有商品所有权转移或彻底删除，因此这条不可变关联也保留了历史卖家，满足 REQ-019。如果以后增加所有权转移，再引入不可变的卖家快照；本期不存两份可写 seller 数据。

`terms : DeliveryTerms` 包含 `deliveryPlace` 和 `deliveryTime`，创建时检查地点说明长度和未来 30 天范围，之后只读。`agreedPrice` 为历史价格快照，不能被当前商品价格替代。`/confirmDeadline = min(createdAt + 24h, deliveryTime)` 可计算，不再保存第二份可变截止时间。

`closure : Closure` 包含终止来源、原因和处理时间。来源区分买家取消、卖家取消、卖家拒绝、到期、平台封禁，用于历史及平台处置展示，不负责控制状态。`firstCompletedAt` 只在首次合法完成时写入。预约的包内方法由 Product 调用，控制器不能分别保存预约后再补改商品。

**ReviewSubmission。** 每次送审保留 `contentSnapshot : ProductSnapshot`，其中包含当次 ProductContent 及图片引用/顺序，是必要的历史快照。审核状态为待审核、已撤回、已通过、已驳回、因封禁关闭，reviewer 在管理员处理前可为空。历史引用及文件不因后续编辑被覆盖或删除；ProductImage 的组合关系仅表示当前图片元数据归属于商品。通过时比较当前与上次获批的完整快照：首次通过或内容变化后通过更新发布时间，未改内容重审沿用；普通取消、拒绝、过期不改发布时间。

**ProductImage。** 保存文件引用、类型、大小和顺序，没有额外引入只用于画图的业务编号。最大数量、格式和大小沿用原需求。违规标记 `ViolationMark` 是商品内部的简单值记录，包含原因、操作者和时间，无须另建一个有生命周期的业务服务。

## 3. 应用与记录类图：幂等与审计各自的职责

`ProductWorkflow.execute(command, actor)` 处理商品、审核与预约命令，`expireIfDue(productID, reservationID)` 由入口检查和到期任务复用。这个应用服务组织鉴权、锁、事务与存储，调用 Product；业务类不依赖 Web、SQL 或日志组件。

`OperationResult` 的唯一键是 `K = (actorRef, action, submissionKey)`。普通 actorRef 来自认证账号；过期任务使用服务端系统身份和按预约编号确定的稳定标记，客户端不能伪造系统身份。`requestDigest` 覆盖动作、目标、页面版本及全部实际业务参数，采用稳定序列化计算；不包含每次网络重试都会改变的请求时间。改变对象、版本、时间、地点或原因后复用同 K 都是内容冲突。

结果只保存 `SUCCESS` 或 `REJECTED`，没有持久化的 `PROCESSING`。`committedState` 保存当时结果，`resultRef` 指向产生的对象。重试返回“原结果 + 当前状态”：原预约创建成功但后来取消，应返回原预约编号、原创建成功和当前已取消，不能重新建单或只返回过时的待确认。

**AuditEntry 是必要的支撑记录，属于需求范围，但不是核心交易实体。** REQ-024～026 明确要求关键操作、敏感读取与记录查询，因此保留。它不判断能否预约，不决定业务状态，不用于恢复幂等结果；可实现为简单表/记录对象，无需专门部署日志服务。

- 每次实际成功变更写一条 `CHANGE`，前后状态可同时包括商品和预约。重复返回结果不追加成功变更记录。
- 管理员查看交付信息记 `ACCESS`，与状态变化分开。查询服务有这种受限的审计追加职责，但不修改商品/预约状态。
- 确定的业务拒绝可以写 `FAILURE` 并保存最终 REJECTED 结果。技术故障先回滚，再尽力独立写 FAILURE；不得额外保存假成功。整体存储故障不承诺审计必然落库。
- 结果解决“同次提交是否已处理”，审计解决“谁在何时对什么做了什么”，因此部分元数据相似有其用途，不应合并成一类。删除了多余结果编号和图中重复返回预约关联。

封禁时预约关闭来源及平台原因一并保存，双方通过“我的预约/处置提醒”查看站内处理结果，提醒从持久化记录派生。本期不额外承诺短信或推送渠道，外部通知 I/O 不放在业务数据库事务中。

业务记录、操作结果与审计继续遵守至少保留 180 天、本期不自动清理的原需求；起算规则仍待 OQ-07 确认。不能因为结果当前已返回客户端就删除幂等结果。

## 4. 两张状态图与类接口逐项对应

所有新动作共有前置条件：认证及当前操作权限通过、页面 version 匹配、已取得商品锁。now 取持锁后、动作判定时的服务器时刻，不使用客户端时间或等待锁前缓存的时刻。命令上下文携带已认证 actor 和 now；方法中显式列出自身需要的业务参数。

| Product 入口 | 当前状态与特有守卫 | 同事务内的协作与结果 |
|---|---|---|
| `edit(content)` | 卖家；草稿/已驳回/已下架 | 保存可编辑内容，状态不变 |
| `submitForReview(now)` | 同上；内容完整合法 | 建立待审快照，商品待审核 |
| `withdrawReview(submissionID, now)` | 卖家；商品待审；编号为当前提交 | 提交 withdraw，商品草稿 |
| `approveReview(submissionID, now)` | 管理员；当前待审提交 | 提交 approve，商品已发布，按规则处理发布时间 |
| `rejectReview(submissionID, reason, now)` | 管理员；当前待审提交；有原因 | 提交 reject，商品已驳回 |
| `takeDown()` | 卖家；已发布；A(p) 为空 | 商品已下架 |
| `createReservation(buyer, terms, now)` | 已发布；无有效预约；非自购；约定合法 | 新预约待确认，固定原价/约定，商品已预约 |
| `acceptReservation(r, now)` | 商品卖家；r 当前待确认；now < 截止 | r.accept，商品仍已预约 |
| `rejectReservation(r, reason, now)` | 商品卖家；r 当前待确认；有原因 | r.reject，商品已发布 |
| `cancelReservation(r, actor, reason, now)` | r 当前有效；待确认仅买家；已确认双方均可且须原因 | r.cancel，商品已发布 |
| `expireReservation(r, now)` | 系统身份；r 当前待确认；now >= 截止 | r.expire，商品已发布，使用独立过期事务 |
| `completeReservation(r, actor, now)` | 仅本预约买家；r 当前已确认 | r.complete，写首次完成时间，商品已售出 |
| `ban(reason, now)` | 管理员；有原因；处于可封禁五种状态 | 有当前预约则 cancelByPlatform；有待审提交则 closeByBan；商品已封禁 |
| `markViolation(reason, actor, now)` | 管理员；有原因；商品已售出 | 追加违规标记，成交状态和历史不变 |

审核/预约包内方法的具体参数见类图。所有关闭操作显式接收 now，统一取自本次动作的服务器判定时刻。授权由应用服务针对锁后当前对象核对，类图方法省略 actor 参数不表示省略权限。

商品状态图的组合外框只是可封禁状态的分组，没有第九个商品状态。图中未画的转换不允许。已封禁不解封，已售出不恢复可售；预约四种终态保留历史，所以不画销毁对象的终止黑圈。后台正常过期时限仍为截止后 60 秒，接受/新建入口也先处理到期记录。

## 5. 组件依赖与共同事务 T

调用方向统一为“请求入口 → 应用服务 → 领域与存储”。商品、预约、审核入口是功能路由，不互相开启子事务；封禁和过期也经过 ProductWorkflow。因此事务只有一个所有者，领域对象不反向依赖数据库。

| 原功能模块 | 本设计承载位置 |
|---|---|
| 账号与权限 | 账号组件：注册、会话、授撤权与对象权限 |
| 商品管理与浏览 | 商品与收藏 API、交易服务商品命令、收藏写入及商品与收藏查询 |
| 审核与违规处置 | 审核 API、交易服务审核/封禁/违规命令 |
| 预约与交付 | 预约 API、交易服务预约命令、到期任务 |
| 操作记录 | 同事务追加 AuditEntry，查询服务按权限检索与敏感访问留痕 |
| 交易统计 | 查询服务读取商品当前状态和已完成预约，按 REQ-027 计算 |

商品相关写事务采用 PostgreSQL READ COMMITTED。先按主键 `SELECT ... FOR UPDATE` 锁住商品，等锁后用**后续新查询**读关联预约/审核，不能沿用等待前的“没有预约”判断。多个对象的详情查询使用同条联表查询或一致读取快照，避免拼出跨提交时点的状态组合。[官方隔离级别说明](https://www.postgresql.org/docs/17/transaction-iso.html)

统一锁顺序为 `BEGIN → K 事务锁 → 商品行锁 → 关联记录 → COMMIT/ROLLBACK`。K 锁采用 `pg_advisory_xact_lock(stableHash64(namespace, actorRef, action, submissionKey))`。固定编码与命名空间，不使用进程随机 hash，不把 requestDigest 放入锁键。哈希碰撞仅导致多等待，结果匹配仍按完整 K 和摘要，最终结果表还保留完整 K 唯一索引。[锁及释放规则](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS)、[事务锁函数](https://www.postgresql.org/docs/17/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS)

K 锁随数据库事务结束释放，没有另行提交的“处理中”记录。连接必须在异常出口回滚/释放，并配置有限的 `lock_timeout`、`statement_timeout`、`idle_in_transaction_session_timeout`，防止应用失联时无限挂起事务。具体秒数是部署参数，不宣称本地已经验证这些配置。

### 5.1 统一处理算法与异常出口

```text
execute(command, actor):
  authenticate(actor)
  K = (actor, command.action, command.submissionKey)
  authorizeRequestTargetOrOwnedResultReference(command.target, K, actor)
  digest = digestOfCanonicalTargetAndAllParameters(command)
  repeat within request deadline:
    BEGIN T
    acquireTransactionKeyLock(K)
    old = readFinalOperationResult(K)       # 取得 K 锁后重查
    if old exists:
      require same digest and target
      authorizeCurrentRead(old.resultRef or old.targetRef, actor)
      response = old.result + readCurrentState(old)
      END T
      return response                      # 不校验旧版本，不执行过期

    p = lockProductRow(command.productID)
    readCurrentReservationsAndReviews(p)    # 锁后新语句重读
    authorizeCurrentAction(p, command, actor)
    now = freshServerTimeAtDecision()
    if command is CREATE or ACCEPT and current pending reservation is due:
      dueReservationID = currentReservation.reservationID
      ROLLBACK T                          # 尚未保存新动作结果
      expireIfDue(p.productID, dueReservationID)  # 独立事务 X0
      continue                            # 从 K 结果检查重新开始

    validate version, state, association, actor and parameters
    if business precondition fails:
      persist final REJECTED and FAILURE audit
      COMMIT T                            # 业务无变动
      return rejection with refresh instruction

    invoke Product business method
    p.version += 1
    persist product and affected reservation/review
    persist final SUCCESS and one CHANGE audit
    check I1..I7
    COMMIT T
    return committed result + current state

  known pre-commit technical failure:
    ROLLBACK T; best-effort independent FAILURE audit
    return retryable error; keep original K
  uncertain COMMIT/connection outcome:
    return outcome unknown; resolve using original K
```

前置读取授权允许服务在内部解析当前账号 K 对应的结果对象，再核对其权限，不先向客户端泄露记录。对于创建重试，授权可以依据原预约的买家身份；不能因商品已预约、已售出或不再公开，就拒绝买家恢复自己的原结果。拿到 K 锁后仍再次核对实际结果关联对象的当前权限。

无权限请求不通过缓存查询泄露结果，读权限/内容冲突时结束事务但不覆盖原结果。确定的业务拒绝在改动业务数据之前识别；数据库写入/约束错误属于技术回滚路径，不能在已中止事务内继续写“最终拒绝”。如果领域守卫在修改内存对象中途拒绝，丢弃该未保存对象后才记录拒绝，不能持久化局部变动。

新建草稿尚无商品行时，使用 K 锁与同事务插入，之后所有商品动作锁已有行。到期任务不采用用户页面版本，在锁内验证指定预约仍是当前待确认且到期的预约；不符合则无变更结束，不新增第二次成功释放日志。

### 5.2 X0：先独立完成合法过期

REQ-018 要求已完成过期不受后续新预约失败影响。因此不能在同一事务里先过期再新建，最后因旧页面失败把过期也回滚。这里先结束未写业务的 T，再独立运行 `expireIfDue`，再重入原命令。不能持着 T 的商品锁让另一连接执行过期，否则会自我阻塞。

X0 用系统过期动作自己的 K，仍按 K → 商品锁排序，重新检查目标预约。若已接受、取消、封禁或出现后继预约，则无变更结束；确实到期时，过期、商品释放、最终结果与成功审计一起提交。后续新动作仍核对客户端原 version，不偷偷用服务器版本替换它。若重入前已有另一同 K 请求完成，则返回该结果。

等待期限用尽可要求原 K 重试，已提交的 X0 保留。创建和接受入口执行这段到期检查，其他动作依自身守卫执行。已确认预约不会因交付时间到达而自动过期。

## 6. 三张时序图解析

### 6.1 正常预约

仅保留买家、API、交易服务、领域与数据库五类参与者。T 覆盖 K 锁、最终结果判断、商品锁、领域操作和全部写入，直到 COMMIT。成功响应在提交确认之后。审计或结果写入失败也使整个 T 回滚，不能先成功预约再补写结果。

### 6.2 两名买家与卖家下架

“撤回商品”要按状态区分：待审核是撤回审核，本来就不可预约；已发布退出销售是下架。此图表现 REQ-009 与 REQ-012 的竞争。三人从相同 version 提交新请求，各自 K 不同，争用同一商品行锁。六种提交次序合并为三类结果：

| 第一个成功提交 | 买家 A | 买家 B | 卖家下架 | 最终状态 |
|---|---|---|---|---|
| A 预约 | 成功 | 拒绝 | 拒绝 | 商品已预约，仅 A 有效 |
| B 预约 | 拒绝 | 成功 | 拒绝 | 商品已预约，仅 B 有效 |
| 卖家下架 | 拒绝 | 拒绝 | 成功 | 商品已下架，无有效预约 |

先获锁但回滚不算成功，下一请求按实际已提交状态判断。不存在下架商品仍有有效预约的结果。卖家下架被拒后，可先按规则拒绝待确认预约或有理由取消已确认预约，再刷新下架；这是新操作，期间其他买家仍可能预约。不能把第一次失败的下架自动延后执行。

### 6.3 幂等重试

第二份同 K 请求等待 K 锁，等待时不执行领域动作；锁到手后重新查询结果，不能沿用锁前“查无结果”的结论。

| 情况 | 持久化事实 | 重试行为 |
|---|---|---|
| 原事务仍执行 | K 仍被持有，无可读最终结果 | 等待；超时只结束当前等待，按原 K 重试 |
| 提交前失败 | 业务、结果、成功审计全回滚，锁释放 | 查无结果，作为尚未执行的原提交重新校验执行 |
| 已提交但响应丢失 | 全部记录保存 | 返回原结果及当前状态，不重做 |
| COMMIT 时断线 | 客户端不知道已提交还是回滚 | 不推断失败，不换 K；取得原 K 后查询判断 |
| 同 K 改内容 | 摘要不同 | 冲突，不覆盖原结果，不返回无关对象数据 |
| 当前无读取权限 | 不能再返回该对象 | 拒绝访问，幂等不绕过权限 |

确定的 REJECTED 同内容重试继续返回原拒绝。修改表单、刷新页面后真正重提须使用新标记。锁超时、存储错误、未知提交结果不缓存为最终业务拒绝，否则可恢复故障会变成永久拒绝。

## 7. 验证范围及后续验收

当前 UML 目录有九个源文件及九张对应 PNG，标识符使用 ID 或 id。初版及人工审核版分别见 Git 标签 `lab2-ai-draft` 和 `lab2-reviewed-v2`。实际用户意见及 AI 修订见《设计审查与修改记录》。

`validation/check_design.py` 是独立的离散状态/事务模型，枚举三方竞争顺序、检查回滚/重试和状态联动、验证图中方法覆盖。它没有连接 PostgreSQL，没有模拟真实连接池、SQL 隔离或网络崩溃恢复。结果见 `validation/验证结果.md`。

实现阶段仍须完成：多连接的 2/100 人预约及下架竞争；同 K 并发、连接终止与事务超时；在各写入点和提交前注入故障；提交后丢响应恢复；旧任务遇到后继预约；截止边界；封禁/完成、取消/完成竞争；数据库重启后恢复；正常 60 秒过期时限和原需求的权限/UI 验收。

采用单体、单库和一个商品交易应用服务，保留交易所需的锁、幂等结果及审计。界面制品及报告见[实验二材料索引](README.md)。

## 8. 商品收藏与关注量

- 登录账号可以收藏他人已发布商品。收藏关系 `Favorite` 通过账号、商品两侧外键关联，并以 `(account_id, product_id)` 为联合主键。重复添加或删除返回相同的收藏状态，关注量按当前关系聚合，可用以 `product_id` 为前缀的索引支持按商品计数。
- 后端设计的添加流程在独立短事务中锁住目标商品行，重读可见状态和卖家后写入收藏关系。取消收藏按当前账号及商品键删除；商品状态变化后仍可删除自己的关系。收藏事务只保存或删除收藏关系，商品版本、预约和商品占用沿用原交易入口。
- 「我的收藏」按当前账号查询。商品当前不可预约时，界面展示已收藏的商品 ID 和取消操作。公开列表只返回已发布商品。可预约商品详情和预约页显示聚合关注量，其他账号的收藏者身份及交付约定仍按各自权限读取。
- 网页原型在浏览器中按演示账号保存收藏，按关系计数。后端集成需验证联合主键、发布状态竞争、账号权限和分页聚合。
