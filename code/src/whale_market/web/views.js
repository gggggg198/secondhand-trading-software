export const PRODUCT = {
  DRAFT: "草稿", PENDING: "待审核", REJECTED: "已驳回", PUBLISHED: "已发布",
  RESERVED: "已预约", SOLD: "已售出", OFFLINE: "已下架", BANNED: "已封禁",
};
export const RESERVATION = {
  PENDING: "待卖家确认", CONFIRMED: "卖家已确认", COMPLETED: "已完成",
  CANCELLED: "已取消", REJECTED: "已拒绝", EXPIRED: "已过期",
};
export const ACTION = {
  draft: "保存草稿", edit: "保存修改", submit: "提交审核", withdraw: "撤回审核",
  approve: "审核通过", reject_review: "驳回审核", offline: "下架商品", reserve: "提交预约",
  accept: "接受预约", reject_reservation: "拒绝预约", cancel: "取消预约",
  complete: "确认交付", ban: "封禁商品", mark_violation: "追加违规标记",
  expire: "到期释放", read_delivery: "查看交付信息", grant_admin: "授予管理权限",
  revoke_admin: "撤销管理权限",
};
const CATEGORIES = ["书籍", "电子产品", "生活用品", "运动用品", "其他"];
const CONDITIONS = ["全新", "九成新", "八成新", "七成新", "有明显使用痕迹"];
const OUTCOME = { SUCCESS: "成功", FAILURE: "失败", ACCESS: "访问" };
const KIND = { product: "商品", reservation: "预约", review: "审核提交", account: "账号" };
const BRAND = "小蓝鲸二手集市";
const LOGO = "/static/assets/blue-whale.png";
const EDITABLE = ["DRAFT", "REJECTED", "OFFLINE"];
const BANNABLE = ["PENDING", "REJECTED", "PUBLISHED", "RESERVED", "OFFLINE"];
const ADMIN = [
  ["review", "商品审核"], ["moderation", "违规处置"], ["platform-bookings", "平台预约"],
  ["accounts", "权限管理"], ["platform-audit", "平台操作记录"], ["platform-stats", "平台交易统计"],
];
const SELLER = [
  ["sell", "我的商品"], ["bookings?scope=sell", "收到的预约"],
  ["audit", "操作记录"], ["stats", "交易统计"],
];
const BEIJING_OFFSET = 8 * 3600 * 1000;

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

export function pathWith(path, entries) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(entries)) {
    if (value !== "" && value != null) params.set(key, value);
  }
  return path + (params.size ? "?" + params : "");
}

export function beijingInput(time = Date.now()) {
  return new Date(time + BEIJING_OFFSET).toISOString().slice(0, 16);
}

export const money = (price) => price == null ? "—" : "¥" + esc(price);
const stamp = (value) => value ? beijingInput(Date.parse(value)).replace("T", " ") : "—";
const titleOf = (product) => product.title || "未命名商品";
const labelOf = (id) => ACTION[id] || id;
const link = (path, text, style = "secondary") => `<a class="btn ${style}" href="#${esc(path)}">${esc(text)}</a>`;
const button = (text, style = "", attrs = "") => `<button class="btn ${style}" ${attrs}>${esc(text)}</button>`;
const input = (name, value = "", attrs = "") => `<input name="${esc(name)}" value="${esc(value)}" ${attrs}>`;
const field = (label, html, hint = "") => `<label class="field"><span>${esc(label)}</span>${html}
  ${hint ? `<small>${esc(hint)}</small>` : ""}</label>`;
const errorBox = '<div class="error" data-error role="alert" tabindex="-1" hidden></div>';
const heading = (title, action = "") => `<div class="heading"><h1>${esc(title)}</h1>${action}</div>`;
const crumb = (path, title) => `<a href="#${esc(path)}" class="crumb">‹ ${esc(title)}</a>`;
const message = (title, text, tone = "") => `<div class="notice ${tone}"><strong>${esc(title)}</strong>${esc(text)}</div>`;
const pairs = (entries) => `<dl class="kv">${entries.map(([key, value]) =>
  `<dt>${esc(key)}</dt><dd>${esc(value)}</dd>`).join("")}</dl>`;
const empty = (title, action = "") => `<section class="empty"><h2>${esc(title)}</h2>${action}</section>`;

function select(name, choices, value, blank) {
  const items = Array.isArray(choices) ? choices.map((item) => [item, item]) : Object.entries(choices);
  return `<select name="${esc(name)}">${blank ? `<option value="">${esc(blank)}</option>` : ""}
    ${items.map(([key, label]) => `<option value="${esc(key)}"${key === value ? " selected" : ""}>${esc(label)}</option>`).join("")}
  </select>`;
}

function status(status, type = "product") {
  const tones = {
    PENDING: "warn", PUBLISHED: "good", RESERVED: "warn", CONFIRMED: "info",
    COMPLETED: "good", SOLD: "accent", BANNED: "danger", REJECTED: "danger",
  };
  const name = (type === "product" ? PRODUCT : RESERVATION)[status] || status;
  return `<span class="chip ${tones[status] || ""}">${esc(name)}</span>`;
}

function photo(id, alt, style = "cover") {
  if (!id) {
    return `<div class="${style} cover-empty"><span>暂无商品图片</span></div>`;
  }
  return `<img class="${style}" src="/api/images/${encodeURIComponent(id)}" alt="${esc(alt)}" loading="lazy">`;
}

function pageFooter(model, route) {
  const pages = Math.max(1, Math.ceil(model.total / model.page_size));
  const pageLink = (number) => pathWith(route.path, { ...route.params, page: number });
  return `<div class="pagination"><small>第 ${model.page} / ${pages} 页 · 共 ${model.total} 条</small>
    <div class="actions">
      ${model.page > 1 ? link(pageLink(model.page - 1), "上一页") : button("上一页", "secondary", "disabled")}
      ${model.page < pages ? link(pageLink(model.page + 1), "下一页") : button("下一页", "secondary", "disabled")}
    </div></div>`;
}

function stateTable(headers, rows) {
  return `<div class="table-wrap"><table><thead><tr>${headers.map((label) =>
    `<th scope="col">${esc(label)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}

function navLink(path, title, on) {
  return `<a href="#${esc(path)}"${on ? ' aria-current="page"' : ""}>${esc(title)}</a>`;
}

function desk(admin, active, body) {
  return `<div class="desk"><nav class="side" aria-label="${admin ? "管理端" : "卖家工作台"}">
    <h2>${admin ? "平台管理" : "卖家工作台"}</h2>
    ${(admin ? ADMIN : SELLER).map(([path, name]) => navLink(path, name, path === active)).join("")}
  </nav><div>${body}</div></div>`;
}

export function frame(actor, route, content, recovery) {
  const isAdminRoute = ADMIN.some(([path]) => path === route.name);
  return `<header class="header"><div class="wrap header-inner">
    <a class="brand" href="#market"><span class="brand-mark"><img src="${LOGO}" width="46" height="46" alt=""></span>${BRAND}</a>
    <nav class="nav" aria-label="主导航">
      ${navLink("market", "逛集市", ["market", "product", "book"].includes(route.name))}
      ${navLink("favorites", "我的收藏", route.name === "favorites")}
      ${actor ? navLink("sell", "我的商品", ["sell", "edit", "manage", "audit", "stats"].includes(route.name)) : ""}
      ${actor ? navLink("bookings", "我的预约", ["bookings", "booking"].includes(route.name)) : ""}
      ${actor?.is_admin ? navLink("review", "管理端", isAdminRoute) : ""}
    </nav>
    <div class="account">${actor
      ? `<span class="account-name">${esc(actor.username)}</span>${link("login", "切换账号", "secondary small")}
        ${button("退出", "ghost small", 'type="button" data-logout')}`
      : link("register", "注册", "ghost") + link("login", "登录", "")}</div>
  </div></header>
  <main id="main-content" class="wrap main" tabindex="-1">
    ${recovery && route.name !== "recover"
      ? `<div class="notice warn pending-result"><span>有一笔提交待确认。</span>${link("recover", "查询原提交结果", "secondary small")}</div>`
      : ""}${content}
  </main><footer class="footer"><div class="wrap">${BRAND} · 校园见面交付</div></footer>`;
}

function productTags(product) {
  const categoryTones = { "电子产品": "blue", "书籍": "violet", "生活用品": "teal", "运动用品": "gold" };
  return `<div class="product-tags">
    ${product.category ? `<span class="tag category-${categoryTones[product.category] || "neutral"}">${esc(product.category)}</span>` : ""}
    ${product.condition ? `<span class="tag condition">${esc(product.condition)}</span>` : ""}
  </div>`;
}

function favoriteButton(product, actor) {
  if (product.seller_id === actor?.id) return "";
  const saved = Boolean(product.is_favorite);
  const label = saved ? "取消收藏" : "收藏";
  return `<button type="button" class="favorite-button" data-favorite="${product.id}" aria-pressed="${saved}"
    aria-label="${label} ${esc(titleOf(product))}" title="${label}"><span aria-hidden="true">${saved ? "♥" : "♡"}</span></button>`;
}

function productCard(product, actor, back = "") {
  const path = pathWith("product/" + product.id, { from: back });
  return `<article class="product-card">
    <a class="card-link" href="#${esc(path)}">
      <div class="card-media">${photo(product.image_ids[0], "")}</div>
      <div class="card-body">
        ${productTags(product)}<h3>${esc(titleOf(product))}</h3>
        <p class="card-description">${esc(product.description)}</p>
        <small class="card-seller">卖家 · ${esc(product.seller_name)}</small>
        <div class="card-bottom"><span class="price">${money(product.price)}</span>
          <span class="interest">关注量 <b>${product.followers}</b></span></div>
      </div>
    </a>${favoriteButton(product, actor)}
  </article>`;
}

export function marketView(model, actor, route) {
  const p = route.params;
  return `<section class="hero"><div class="hero-copy"><h1>${BRAND}</h1><p>挑选校园闲置，预约后和同学见面交付。</p></div>
    <div class="hero-mark" aria-hidden="true"><img src="${LOGO}" alt=""></div></section>
    <form class="panel filters" data-filter="market">
      ${field("关键词", input("q", p.q, 'maxlength="60" placeholder="搜索商品"'))}
      ${field("分类", select("category", CATEGORIES, p.category, "全部分类"))}
      ${field("最低价（元）", input("minimum", p.minimum, 'inputmode="decimal" placeholder="不限"'))}
      ${field("最高价（元）", input("maximum", p.maximum, 'inputmode="decimal" placeholder="不限"'))}
      <div class="actions">${link("market", "重置")}${button("筛选商品")}</div>${errorBox}
    </form>
    <div class="section-heading"><h2>可预约商品</h2><span class="muted">共 ${model.total} 件</span></div>
    ${model.items.length
      ? `<div class="cards">${model.items.map((product) => productCard(product, actor)).join("")}</div>`
      : empty("没有匹配的商品", link("market", "查看全部商品"))}
    ${pageFooter(model, route)}`;
}

export function favoritesView(model, actor, route) {
  const rows = model.items.map(({ product_id, product }) => product
    ? productCard(product, actor, "favorites")
    : `<article class="panel saved-unavailable"><div><h3>商品当前不可预约</h3><small>商品编号 ${product_id}</small></div>
      ${button("取消收藏", "secondary small", `type="button" data-favorite="${product_id}" aria-pressed="true"`)}</article>`);
  return heading("我的收藏") + (rows.length
    ? `<div class="cards">${rows.join("")}</div>${pageFooter(model, route)}`
    : empty("还没有收藏商品", link("market", "去逛集市", "")));
}

export function publicProduct(product, actor, route) {
  const self = actor?.id === product.seller_id;
  const available = product.status === "PUBLISHED";
  const next = "book/" + product.id;
  const action = self ? link("manage/" + product.id, "管理我的商品")
    : actor ? link(next, "预约商品", "") : link(pathWith("login", { next }), "登录后预约", "");
  const back = route.params.from === "favorites" ? "favorites" : "market";
  return `${crumb(back, back === "favorites" ? "返回我的收藏" : "返回集市")}<div class="split">
    <section class="panel">
      <div data-main-photo>${photo(product.image_ids[0], titleOf(product), "cover detail-photo")}</div>
      ${product.image_ids.length > 1 ? `<div class="gallery" aria-label="商品图片">${product.image_ids.map((id, index) =>
        `<button type="button" class="thumb" data-photo="${id}" aria-label="查看第 ${index + 1} 张图片"
          aria-pressed="${index === 0}">${photo(id, "")}</button>`).join("")}</div>` : ""}
      <h2>商品描述</h2><p class="desc">${esc(product.description)}</p>
    </section><section class="panel detail-copy">
      ${status(product.status)}<h1>${esc(titleOf(product))}</h1>
      <div class="detail-meta"><p class="price large">${money(product.price)}</p><span>关注量 ${product.followers}</span></div>
      ${productTags(product)}${pairs([["商品编号", product.id], ["卖家", product.seller_name]])}
      <div class="actions">${available ? action + favoriteButton(product, actor) : link(back, "查看其他商品")}</div>
    </section></div>`;
}

export function authView(register, next = "") {
  const title = register ? "注册账号" : "登录";
  const other = pathWith(register ? "login" : "register", { next });
  return `<section class="panel auth-form">
    ${heading(title)}<form class="form-stack" data-form="${register ? "register" : "login"}" data-next="${esc(next)}">
      ${field("用户名", input("username", "", 'required autocomplete="username" pattern="[A-Za-z0-9_]{4,20}" maxlength="20"'), register ? "4 至 20 位字母、数字或下划线" : "")}
      ${field("密码", input("password", "", `type="password" required minlength="10" maxlength="64" autocomplete="${register ? "new-password" : "current-password"}"`))}
      ${register ? field("确认密码", input("confirm", "", 'type="password" required minlength="10" maxlength="64" autocomplete="new-password"')) : ""}
      ${errorBox}<div class="actions">${button(title)}${link(other, register ? "已有账号，去登录" : "注册新账号")}</div>
    </form></section>`;
}

function commandButton(action, payload, text = ACTION[action], style = "secondary", needsReason = false) {
  return button(text, style, `type="button" data-command="${esc(JSON.stringify({ action, ...payload }))}"
    ${needsReason ? "data-requires-reason" : ""}`);
}

export function productList(model, route, admin = false) {
  const reviewQueue = route.name === "review";
  const title = admin ? (reviewQueue ? "商品审核" : "违规处置") : "我的商品";
  const detailPage = admin ? route.name : "manage";
  const rows = model.items.map((product) => `<tr>
    <td><a href="#${detailPage}/${product.id}">${esc(titleOf(product))}</a><small>编号 ${product.id}</small></td>
    ${admin ? `<td>${esc(product.seller_name)}</td>` : ""}<td>${status(product.status)}</td>
    <td>${money(product.price)}</td><td>${stamp(product.published_at)}</td>
    <td>${link(detailPage + "/" + product.id, "查看", "secondary small")}</td>
  </tr>`);
  const filters = `<form class="panel filters" data-filter="${route.name}">
    ${field("关键词", input("q", route.params.q, 'maxlength="60"'))}
    ${reviewQueue ? "" : field("商品状态", select("state", PRODUCT, route.params.state, "全部状态"))}
    <div class="actions">${button("查询")}</div>${errorBox}
  </form>`;
  const headers = ["商品", ...(admin ? ["卖家"] : []), "状态", "价格", "发布时间", "操作"];
  return desk(admin, route.name, heading(title, admin ? "" : link("edit/new", "发布商品", "")) + filters
    + (rows.length ? stateTable(headers, rows) : empty(reviewQueue ? "暂无待审核商品" : "暂无商品"))
    + pageFooter(model, route));
}

export function photosView(ids) {
  return ids.map((id, index) => `<figure>${photo(id, "商品图片 " + (index + 1))}
    ${button("移除", "secondary small", `type="button" data-remove-photo="${id}" aria-label="移除第 ${index + 1} 张图片"`)}
  </figure>`).join("");
}

export function editView(product) {
  const current = Boolean(product);
  if (current && !EDITABLE.includes(product.status)) {
    return desk(false, "sell", empty("当前状态不能编辑", link("manage/" + product.id, "返回商品")));
  }
  const images = product?.image_ids || [];
  return desk(false, "sell", heading(current ? "编辑商品" : "发布商品") + `<section class="panel">
    <form class="form-stack" data-form="edit" data-id="${product?.id || ""}"
      data-version="${product?.version || ""}" data-images="${esc(JSON.stringify(images))}">
      ${field("标题", input("title", product?.title, 'maxlength="60"'))}
      ${field("描述", `<textarea name="description" maxlength="2000" rows="5">${esc(product?.description)}</textarea>`)}
      <div class="form-grid">
        ${field("分类", select("category", CATEGORIES, product?.category, "请选择"))}
        ${field("成色", select("condition", CONDITIONS, product?.condition, "请选择"))}
        ${field("价格（元）", input("price", product?.price ?? "", 'inputmode="decimal"'))}
      </div>
      ${field("商品图片", '<input type="file" name="photos" accept="image/png,image/jpeg" multiple>', "最多 5 张，每张不超过 5 MiB")}
      <div class="edit-photos" data-photos>${photosView(images)}</div>
      ${errorBox}<div class="actions">${button(current ? "保存修改" : "保存草稿")}${link("sell", "返回")}</div>
    </form></section>`);
}

export function managedProduct(product, actor, route) {
  const admin = route.name !== "manage";
  const owner = product.seller_id === actor.id;
  const review = product.review;
  const payload = { product_id: product.id, version: product.version };
  let controls = "";
  if (!admin && owner) {
    if (EDITABLE.includes(product.status)) {
      controls += link("edit/" + product.id, "编辑商品") + commandButton("submit", payload, ACTION.submit, "");
    }
    if (product.status === "PENDING" && review) {
      controls += commandButton("withdraw", { ...payload, review_id: review.id });
    }
    if (product.status === "PUBLISHED") controls += commandButton("offline", payload);
  }
  if (admin && actor.is_admin) {
    if (product.status === "PENDING" && review && route.name === "review") {
      const reviewPayload = { ...payload, review_id: review.id };
      controls += commandButton("approve", reviewPayload, ACTION.approve, "") + commandButton("reject_review", reviewPayload);
    }
    if (BANNABLE.includes(product.status) && route.name === "moderation") controls += commandButton("ban", payload, ACTION.ban, "danger");
    if (product.status === "SOLD") controls += commandButton("mark_violation", payload);
  }
  const currentContent = product.status === "PENDING" && review?.content ? review.content : product;
  const body = `${crumb(admin ? route.name : "sell", "返回列表")}
    ${heading(titleOf(currentContent), status(product.status))}<section class="panel stack">
      ${pairs([["商品编号", product.id], ["卖家", product.seller_name],
        ["分类", currentContent.category], ["成色", currentContent.condition],
        ["价格", currentContent.price == null ? "—" : "¥" + currentContent.price],
        ["发布时间", stamp(product.published_at)], ["本次送审编号", review?.id ?? "—"]])}
      <p class="desc">${esc(currentContent.description)}</p>
      ${currentContent.image_ids.length
        ? `<div class="gallery">${currentContent.image_ids.map((id) => photo(id, "商品图片")).join("")}</div>`
        : ""}
      ${review?.reason ? message("审核处理原因", review.reason) : ""}
      ${product.ban_reason ? message("封禁原因", product.ban_reason, "danger") : ""}
      ${(product.violations || []).map((entry) => message("违规记录 · " + stamp(entry.recorded_at), entry.reason, "warn")).join("")}
      <div class="actions">${controls}</div>
    </section>`;
  return desk(admin, admin ? route.name : "sell", body);
}

export function bookView(product, actor) {
  if (product.status !== "PUBLISHED" || actor.id === product.seller_id) {
    return empty("商品当前不可预约", link("market", "返回集市"));
  }
  return `${crumb("product/" + product.id, "返回商品")}${heading("提交预约")}
    <div class="split"><section class="panel stack"><h2>${esc(titleOf(product))}</h2>
      <div class="price large">${money(product.price)}</div>
      ${pairs([["卖家", product.seller_name], ["关注量", product.followers]])}
    </section><section class="panel"><form class="form-stack" data-form="reserve"
      data-id="${product.id}" data-version="${product.version}">
      ${field("校园公共交付地点", input("location", "", 'required minlength="2" maxlength="100"'), "请勿填写宿舍号等私人地址")}
      ${field("交付时间（北京时间）", input("meeting_at", beijingInput(Date.now() + 86400000), 'type="datetime-local" required'), "在未来 30 天内选择")}
      ${errorBox}<div class="actions">${button("提交预约")}${link("product/" + product.id, "返回")}</div>
    </form></section></div>`;
}

export function bookingList(model, route, admin = false) {
  const scope = admin ? "all" : (route.params.scope === "sell" ? "sell" : "buy");
  const rows = model.items.map((row) => `<tr><td><a href="#booking/${row.id}">${esc(row.product_title)}</a>
    <small>预约编号 ${row.id}</small></td><td>${status(row.status, "booking")}</td>
    <td>${esc(row.buyer_name)}</td><td>${esc(row.seller_name)}</td><td>${stamp(row.created_at)}</td>
    <td>${link("booking/" + row.id, "查看", "secondary small")}</td></tr>`);
  const filters = `<form class="panel filters" data-filter="${route.name}">
    ${scope === "all" ? "" : field("预约方向", select("scope", { buy: "我发起的", sell: "我收到的" }, scope))}
    ${field("预约状态", select("status", RESERVATION, route.params.status, "全部状态"))}
    <div class="actions">${button("查询")}</div>${errorBox}
  </form>`;
  const content = heading(admin ? "平台预约" : "我的预约") + filters
    + (rows.length ? stateTable(["商品", "状态", "买家", "卖家", "提交时间", "操作"], rows) : empty("暂无对应的预约"))
    + pageFooter(model, route);
  if (admin) return desk(true, "platform-bookings", content);
  return scope === "sell" ? desk(false, "bookings?scope=sell", content) : content;
}

export function bookingView(record, actor) {
  const seller = record.seller_id === actor.id;
  const buyer = record.buyer_id === actor.id;
  const payload = { product_id: record.product_id, reservation_id: record.id, version: record.product_version };
  let controls = "";
  if (record.status === "PENDING" && seller) {
    controls += commandButton("accept", payload, ACTION.accept, "") + commandButton("reject_reservation", payload);
  }
  if ((buyer && record.status === "PENDING") || ((buyer || seller) && record.status === "CONFIRMED")) {
    controls += commandButton("cancel", payload, ACTION.cancel, "secondary", record.status === "CONFIRMED");
  }
  if (buyer && record.status === "CONFIRMED") controls += commandButton("complete", payload, ACTION.complete, "");
  const back = seller ? "bookings?scope=sell" : buyer ? "bookings" : "platform-bookings";
  const delivery = record.delivery_visible
    ? pairs([["地点", record.location], ["交付时间", stamp(record.meeting_at)],
      ...(record.status === "PENDING" ? [["卖家确认截止", stamp(record.deadline)]] : [])])
    : button("查看交付信息", "secondary", `type="button" data-delivery="${record.id}"`);
  const content = `${crumb(back, "返回预约列表")}${heading("预约详情", status(record.status, "booking"))}
    <div class="split"><section class="panel">
      <h2>${esc(record.product_title)}</h2>
      ${pairs([["预约编号", record.id], ["商品编号", record.product_id], ["买家", record.buyer_name],
        ["卖家", record.seller_name], ["约定价格", "¥" + record.price], ["提交时间", stamp(record.created_at)],
        ["完成时间", stamp(record.completed_at)]])}
      ${record.reason ? message(record.platform_cancelled ? "平台取消" : "处理原因", record.reason, "warn") : ""}
    </section><section class="panel stack"><h2>交付约定</h2>${delivery}<div class="actions">${controls}</div></section></div>`;
  return buyer || seller ? content : desk(true, "platform-bookings", content);
}

export function auditView(model, route, admin) {
  const p = route.params;
  const rows = model.items.map((row) => `<tr>
    <td>${stamp(row.recorded_at)}</td><td>${esc(row.actor_name || "系统")}</td><td>${esc(labelOf(row.action))}</td>
    <td>${esc(KIND[row.target_kind])} ${esc(row.target_id ?? "—")}</td><td>${esc(OUTCOME[row.outcome])}</td>
    <td>${esc(row.before_state || "—")} → ${esc(row.after_state || "—")}</td>
    <td>${esc(row.reason || "—")}</td></tr>`);
  return desk(admin, route.name, heading(admin ? "平台操作记录" : "我的操作记录") + `
    <form class="panel filters audit-filters" data-filter="${route.name}">
      ${field("商品编号", input("product_id", p.product_id, 'type="number" min="1"'))}
      ${field("预约编号", input("reservation_id", p.reservation_id, 'type="number" min="1"'))}
      ${field("对象类型", select("target_kind", KIND, p.target_kind, "全部对象"))}
      ${field("对象编号", input("target_id", p.target_id, 'type="number" min="1"'))}
      ${field("操作人编号", input("operator_id", p.operator_id, 'type="number" min="1"'))}
      ${field("动作", select("action", ACTION, p.action, "全部动作"))}
      ${field("结果", select("outcome", OUTCOME, p.outcome, "全部结果"))}
      ${field("开始日期", input("start", p.start, 'type="date"'))}
      ${field("结束日期", input("end", p.end, 'type="date"'))}
      <div class="actions">${link(route.name, "重置")}${button("查询")}</div>${errorBox}
    </form>${rows.length ? stateTable(["时间", "操作人", "动作", "对象", "结果", "前后状态", "原因"], rows) : empty("没有匹配的操作记录")}
    ${pageFooter(model, route)}`);
}

export function statsView(model, route, admin) {
  const counts = Object.entries(model.counts).map(([state, value]) =>
    `<div class="status-row">${status(state)}<strong>${value}</strong></div>`).join("");
  return desk(admin, route.name, heading(admin ? "平台交易统计" : "我的交易统计") + `
    <form class="panel filters" data-filter="${route.name}">
      ${field("开始日期", input("start", model.start, 'type="date" required'))}
      ${field("结束日期（不含当天）", input("end", model.end, 'type="date" required'))}
      <div class="actions">${button("更新统计")}</div>${errorBox}
    </form>
    <div class="split"><section class="panel"><h2>商品当前状态数量</h2>${counts}</section>
      <section class="panel"><h2>区间成交</h2>${pairs([["成交笔数", model.completed],
        ["约定总额", "¥" + model.total_amount], ["统计时区", "北京时间"]])}</section></div>`);
}

export function rolesView(model, route) {
  const rows = model.items.map((account) => `<tr><td>${account.id}</td><td>${esc(account.username)}</td>
    <td>${account.is_admin ? "管理员" : "普通账号"}</td>
    <td>${button(account.is_admin ? "撤销管理权限" : "授予管理权限", "secondary small",
      `type="button" data-role="${account.id}" data-grant="${!account.is_admin}"`)}</td></tr>`);
  return desk(true, "accounts", heading("权限管理", `<span class="muted">${model.administrator_count} 位管理员</span>`) + `
    <form class="panel filters" data-filter="accounts">${field("用户名", input("q", route.params.q, 'maxlength="20"'))}
      <div class="actions">${button("查询")}</div>${errorBox}
    </form>
    ${rows.length ? stateTable(["编号", "用户名", "权限", "操作"], rows) : empty("没有匹配的账号")}
    ${pageFooter(model, route)}`);
}

export function recoveryView(pending) {
  if (!pending) return heading("查询提交结果") + empty("没有待确认的提交", link("market", "返回集市"));
  return heading("查询提交结果") + `<section class="panel stack">
    ${message(labelOf(pending.action), "提交结果尚未确认。使用原提交标记查询，系统会恢复已保存的结果。", "warn")}
    ${pairs([["商品编号", pending.product_id ?? "新建商品"], ["提交标记", pending.submission_key]])}
    <div class="actions">${button("查询原提交", "", 'type="button" data-retry-command')}</div></section>`;
}

export function commandDialog(command, requireReason, title = ACTION[command.action]) {
  return `<form class="form-stack" data-dialog-form>
    <h2 id="dialog-title">${esc(title)}</h2>
    ${command.action === "complete" ? '<label class="check"><input name="received" type="checkbox" required> 我已收到线下交付的实物</label>' : ""}
    ${requireReason || command.action === "cancel"
      ? field("原因", `<textarea name="reason" maxlength="200" ${requireReason ? "required" : ""}></textarea>`) : ""}
    ${errorBox}<div class="actions">
      ${button("确认", ["ban", "offline", "cancel", "revoke_admin"].includes(command.action) ? "danger" : "")}
      ${button("返回", "secondary", 'type="button" data-close-dialog')}
    </div></form>`;
}

export function failedView(text, back = "market") {
  return heading("暂时无法打开") + message("请检查后重试", text, "danger") + link(back, "返回");
}
