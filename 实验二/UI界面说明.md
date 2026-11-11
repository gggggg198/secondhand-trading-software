# 南大集市 UI 设计

南大集市面向校园单件二手交易。访客浏览公开商品，普通账号可作为买家或卖家完成预约和线下交付，管理员负责审核、违规处置和权限管理。原型采用 1440 × 960 的桌面画板，账号、编号、价格、日期和照片均为演示数据。

在 Chrome 或 Edge 中运行网页时，请打开[本地前端首页](web/index.html)。可以使用演示账号操作商品、审核和预约，并查看实际更新后的页面状态。[网页打开与操作说明](web/README.md)

在 draw.io 中打开[可编辑原型](UI设计/南大集市_UI原型.drawio)，通过底部页面标签查看 21 个画板。界面中的文字、表格、状态标签、按钮和图表由独立图形组成，可以直接编辑。带链接的按钮和导航用于演示主要页面间的跳转，表单输入、查询和状态更新由画板示例表达。课程所需的 PNG 在 [UI界面](UI界面/) 下，文件名与画板标签一致。[draw.io 文件与导出说明](https://www.drawio.com/docs/manual/export/export-diagram/)

## 六个功能模块

| 模块 | 对应界面 | 功能与操作 |
| --- | --- | --- |
| 账号与权限 | [03 账号登录](UI界面/03_账号登录.png) · [04 普通账号注册](UI界面/04_普通账号注册.png) · [16 权限管理](UI界面/16_权限管理.png) | 访客可返回集市。普通账号使用用户名和密码，注册时显示格式限制。管理员查询账号并确认授权或撤权，剩余一名有效管理员时禁用其撤权操作。 |
| 商品管理与浏览 | [01 集市浏览](UI界面/01_集市浏览.png) · [02 商品详情](UI界面/02_商品详情.png) · [05 我的商品](UI界面/05_我的商品.png) · [06 编辑商品](UI界面/06_编辑商品.png) | 公开页组合筛选关键词、分类和价格，按发布时间排序，每页 20 件，仅列出可预约商品。卖家按八种状态查看自己的商品，保存草稿、送审、撤回待审提交或下架符合条件的商品。已预约行显示当前预约入口及不可下架状态。 |
| 审核与违规处置 | [14 商品审核](UI界面/14_商品审核.png) · [15 违规处置](UI界面/15_违规处置.png) | 管理员核对带提交编号的送审快照，审核通过或有理由驳回。封禁存在有效预约的商品时先显示联动影响，再确认封禁及平台取消。已售出商品提供追加违规标记入口。 |
| 预约与交付 | [07 提交预约](UI界面/07_提交预约.png) · [08 买家预约列表](UI界面/08_买家预约列表.png) · [09 卖家处理预约](UI界面/09_卖家处理预约.png) · [10 买家确认交付](UI界面/10_买家确认交付.png) · [11 交易完成](UI界面/11_交易完成.png) · [12 预约结果待确认](UI界面/12_预约结果待确认.png) · [13 商品状态已变](UI界面/13_商品状态已变.png) · [21 预约已过期](UI界面/21_预约已过期.png) | 买家填写校园公共地点和交付时间。卖家在截止前接受或有理由拒绝。已确认后双方可填写原因取消。买家收到实物后确认交付，详情显示原约定、原价格和首次完成时间。 |
| 操作记录 | [17 平台操作记录](UI界面/17_平台操作记录.png) · [18 我的操作记录](UI界面/18_我的操作记录.png) | 按对象 ID、操作人、动作、结果和时间组合查询。管理员查看平台记录，普通账号查看本人参与的交易和有权读取的记录。失败行保留原因及操作前后状态，获授权管理员查看交付信息时产生访问记录。 |
| 交易统计 | [19 卖家交易统计](UI界面/19_卖家交易统计.png) · [20 平台交易统计](UI界面/20_平台交易统计.png) | 卖家查看本人商品，管理员查看平台汇总。成交统计按北京时间左闭右开区间，以首次完成时间计笔数、以预约时价格计约定总额。当前商品各状态数量单独展示，保持当前查询时的口径。 |

## 典型使用流程

1. 访客在 01 选择机械键盘，进入 02。通过“登录后预约”进入 03。演示登录后进入 07，提交交付约定后在 08 查看预约 R-0421 及确认截止时间。04 演示普通账号注册。
2. 卖家在 05 查看商品 P-1042 的当前预约，从 09 接受或拒绝。该样例于 11 月 11 日 17:20 创建，交付时间为 11 月 14 日 16:30，因此确认截止为 11 月 12 日 17:20。接受后时间、地点和预约时价格沿用原约定。
3. 买家在 10 核对约定并确认已收到实物，在 11 查看首次完成时间。交易统计中的“约定总额”按预约价格汇总，线下付款由双方自行办理。
4. 请求超时且提交结果未知时，12 提供“查询本次结果”。系统用原用户、动作、提交标记及同一请求内容恢复结果。13 演示另一个买家抢先预约后的明确冲突。21 保留已过期预约的历史约定，提供返回集市入口。
5. 管理员在 14 对待审核的 P-1090 当前提交作决定。15 使用另一件商品 P-1074 和预约 R-0433 演示平台封禁及联动取消，同时展示已售出商品的违规标记入口。

画板用不同时间点展示同一条交易的前后状态。页面标签可用来检查其他角色和分支。已在 draw.io 查看器中点验 01 → 02 → 03 → 07 → 08 的页面链接。

## 状态、权限与反馈

| 场景 | 界面行为 |
| --- | --- |
| 待审核、已发布和已预约 | 待审核显示“撤回审核”。已发布且无有效预约显示“下架”。已预约显示“查看预约”，卖家结束当前预约后，才可按最新状态下架。 |
| 预约双方的可用动作 | 待卖家确认时，买家可以取消，卖家可以接受或填写原因拒绝。卖家已确认时，双方取消均需原因，只有当前预约的买家显示“确认交付完成”。终态保留原约定和历史结果。 |
| 私有交付信息 | 公开详情显示商品及卖家，不展示具体交付地点和时间。预约详情面向本单买卖双方和获授权管理员。管理员查看后记录访问，权限由服务端按该预约核对。 |
| 价格或价格区间不合法 | 就地提示“价格需在 ¥0.01–¥100000.00 之间，最多两位小数”或“最低价不能高于最高价”，焦点回到对应字段并保留输入。 |
| 页面状态变化 | 提示“商品或预约状态已变化，请刷新后再操作”。已有有效预约时显示 13 的冲突提示，下架或封禁后引导返回集市。 |
| 截止时间已到 | 当前待确认预约失去接受入口，显示过期原因与可执行的下一步。已确认预约超过交付时间时可提醒双方。 |
| 服务暂不可用 | 已知未执行时提示“服务暂不可用，请稍后重试”。提交结果未知时展示 12，通过本次请求查询结果，取得明确状态后再决定是否发起新操作。 |

实现时，登录按用户名、密码和登录按钮的顺序获得焦点。查询按关键词、分类、最低价、最高价、重置、筛选按钮和结果项组织键盘访问。预约按交付时间、地点和提交按钮组织焦点。标签和错误文案随控件可读，状态同时使用文字与颜色。关键词匹配范围、日志的时间端点和分页仍按实验一待确认事项处理。

## 本轮 AI 使用记录

| 场景 | 生成结果 | 优点与局限 | 本轮修订 |
| --- | --- | --- | --- |
| 根据实验一和已审查的 UML 生成 UI | draw.io 多页原型、21 张界面 PNG、模块说明和流程示例。 | 能快速复用布局并联动多个角色页面。生成时可能混淆公开列表和卖家状态，或把网络超时解释为提交失败。 | 逐一核对权限范围、有效预约占用、封禁联动和统计口径。将明确冲突与结果未知拆成两个页面。分开公开商品和送审草稿的样例文案，并检查 21 张导出图。 |
| 为商品卡片生成样例照片 | 使用内置 imagegen 生成四格样例照片，原图见[商品样例原图](UI设计/素材/商品样例原图.png)。 | 一次得到光线和色调协调的样例素材。商品图片为模拟素材，具体型号和交易信息由界面演示数据决定。 | 将四格分成独立图片后嵌入画板。价格、商品名称、状态和按钮文字由 draw.io 图元承载，便于后续调整。 |

本轮 UI 和导出由 AI 辅助制作和核对，先前 UML 的十条评审意见来自用户。后续实际人工调整可以用下一次 Git 提交记录，并将相应判断及修改原因写入实验报告。

内置 imagegen 使用的提示词如下。

> Use case: product-mockup. A single landscape image containing exactly four separate realistic second-hand item listing photographs, a precise 2×2 contact sheet with equal rectangular quadrants. The four tile boundaries are exactly the vertical and horizontal center lines. No gutter, border, headings, text overlays, people, hands, trademarks, or watermarks. Top left: a compact ivory 75-percent mechanical computer keyboard with dark charcoal key legends and one pale sage escape key, three-quarter overhead view on a muted jade desk. Top right: a stack of two slightly used university computer science textbooks, one burgundy cover and one dark blue cover, on a warm tan tabletop, no legible cover branding. Bottom left: a cream folding LED study desk lamp, turned on with warm light, on pale timber against soft ivory background. Bottom right: a dark sage nylon day backpack with simple woven straps, on a soft blue-gray bench. Each object is centered with breathing room on every side, fully contained within its own quadrant. Realistic student second-hand sale photography, thoughtful natural window lighting, subtle wear, clean and believable materials, distinctive but harmonious scene colors. Use four edge-to-edge photos; exact straight center cuts so each tile can be placed into a product card.
