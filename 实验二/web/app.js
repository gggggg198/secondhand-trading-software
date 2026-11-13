(function () {
  "use strict";

  const D = globalThis.MarketDemo;
  const BRAND = "小蓝鲸二手集市";
  const LOGO = "assets/blue-whale.png";
  const site = document.getElementById("site");
  const dialog = document.getElementById("action-dialog");
  const toast = document.getElementById("notice");
  const SESSION = "nju-market-demo-session";
  const PENDING = "nju-market-demo-pending";

  function browserStorage(name) {
    try { return window[name]; } catch { return null; }
  }

  const service = D.createService(browserStorage("localStorage"));
  const session = browserStorage("sessionStorage");
  function sessionRead(key) {
    try { return session?.getItem(key) ?? null; } catch { return null; }
  }
  function sessionWrite(key, value) {
    try {
      if (value === null) session?.removeItem(key);
      else session?.setItem(key, value);
    } catch { /* A tab can keep its state in memory. */ }
  }

  let actorID = sessionRead(SESSION);
  let pending = {};
  try { pending = JSON.parse(sessionRead(PENDING) || "{}") || {}; } catch { /* Read old data as an empty session. */ }
  let toastTimer;
  let snapshot;
  let editState;
  let delivery;
  let dialogAction;

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);
  }
  const money = (cents) => cents == null ? "—" : "¥" + (cents / 100).toFixed(2);
  const stamp = (time) => time == null ? "—" : D.dateInput(time).replace("T", " ");
  const titleOf = (product) => product?.title || "未命名商品";
  const person = (ID) => ID === "system" ? "系统" : snapshot.accounts.find((item) => item.ID === ID)?.name || "未知账号";
  const field = (label, html, note = "") => `<label class="field"><span>${esc(label)}</span>${html}${note ? `<small>${esc(note)}</small>` : ""}</label>`;
  const input = (name, value = "", options = "") => `<input name="${esc(name)}" value="${esc(value)}" ${options}>`;
  const reasonText = (name = "reason") => `<textarea name="${esc(name)}" required maxlength="200" placeholder="填写原因"></textarea>`;
  const link = (path, text, style = "secondary") => `<a class="btn ${esc(style)}" href="#${esc(path)}">${esc(text)}</a>`;
  const button = (text, style = "", attrs = "") => `<button class="btn ${style}" ${attrs}>${esc(text)}</button>`;
  const errorBox = '<div class="error" data-error role="alert" hidden></div>';

  function select(name, items, value, empty) {
    const entries = Array.isArray(items) ? items.map((item) => [item, item]) : Object.entries(items);
    return `<select name="${esc(name)}">${empty ? `<option value="">${esc(empty)}</option>` : ""}
      ${entries.map(([key, label]) => `<option value="${esc(key)}"${key === value ? " selected" : ""}>${esc(label)}</option>`).join("")}</select>`;
  }

  function statusChip(type, status) {
    const product = type === "product";
    const tones = product
      ? { PENDING: "warn", PUBLISHED: "good", RESERVED: "warn", SOLD: "accent", BANNED: "danger", REJECTED: "danger" }
      : { PENDING: "warn", ACCEPTED: "info", COMPLETED: "good", REJECTED: "danger" };
    return `<span class="chip ${tones[status] || ""}">${esc((product ? D.PRODUCTS : D.BOOKINGS)[status])}</span>`;
  }

  function image(src, alt, classes = "cover") {
    return D.validImage(src || "")
      ? `<img class="${classes}" src="${esc(src)}" alt="${esc(alt)}">`
      : `<div class="${classes} cover-empty"><span>暂无商品图片</span></div>`;
  }

  const heading = (title, subtitle = "", right = "") => `<div class="heading"><div><h1>${esc(title)}</h1>
    ${subtitle ? `<p>${esc(subtitle)}</p>` : ""}</div>${right}</div>`;
  const crumb = (path, label) => `<a class="crumb" href="#${esc(path)}">‹ ${esc(label)}</a>`;
  const notice = (title, detail, tone = "") => `<div class="notice ${tone}"><strong>${esc(title)}</strong>${esc(detail)}</div>`;
  const pairs = (entries) => `<dl class="kv">${entries.map(([key, value]) => `<dt>${esc(key)}</dt><dd>${esc(value)}</dd>`).join("")}</dl>`;
  const empty = (title, detail, action = "") => `<section class="empty"><h2>${esc(title)}</h2><p>${esc(detail)}</p>${action}</section>`;

  function route() {
    const [path, ...query] = (window.location.hash.slice(1) || "market").split("?");
    const [name, id] = path.split("/");
    return { name, id, params: new URLSearchParams(query.join("?")), full: path + (query.length ? "?" + query.join("?") : "") };
  }

  function pathWith(path, entries) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(entries)) if (value) params.set(key, value);
    return path + (params.size ? "?" + params.toString() : "");
  }

  function go(path) {
    const next = "#" + path;
    if (window.location.hash === next) render();
    else window.location.hash = next;
  }

  function pagination(items, r, path) {
    const pages = Math.max(1, Math.ceil(items.length / 20));
    const page = Math.min(pages, Math.max(1, Math.trunc(Number(r.params.get("page")) || 1)));
    const pageLink = (number) => pathWith(path, { ...Object.fromEntries(r.params), page: String(number) });
    return {
      items: items.slice((page - 1) * 20, page * 20),
      footer: `<div class="pagination"><small>每页 20 条 · 第 ${page} / ${pages} 页 · 共 ${items.length} 条</small>
        <div class="actions">${page > 1 ? link(pageLink(page - 1), "上一页") : button("上一页", "", "disabled")}
        ${page < pages ? link(pageLink(page + 1), "下一页") : button("下一页", "", "disabled")}</div></div>`
    };
  }

  const sellerTabs = [["seller", "我的商品"], ["bookings?role=seller", "预约处理"], ["logs", "操作记录"], ["stats", "交易统计"]];
  const adminTabs = [["review", "商品审核"], ["moderation", "违规处置"], ["admin-bookings", "平台预约"],
    ["admin-accounts", "权限管理"], ["admin-logs", "操作记录"], ["admin-stats", "交易统计"]];
  const tabLink = (path, text, on) => `<a href="#${esc(path)}"${on ? ' aria-current="page"' : ""}>${esc(text)}</a>`;
  const adminRoutes = new Set(adminTabs.map(([path]) => path));

  function header(r) {
    const me = snapshot.actor;
    return `<header class="header"><div class="wrap header-inner">
      <a class="brand" href="#market"><span class="brand-mark"><img src="${LOGO}" alt="" width="46" height="46"></span>${BRAND}</a>
      <nav class="nav" aria-label="主导航">
        ${tabLink("market", "逛集市", ["market", "product"].includes(r.name))}
        ${tabLink("favorites", "我的收藏", r.name === "favorites")}
        ${me ? tabLink("seller", "我的商品", ["seller", "edit", "logs", "stats"].includes(r.name)) : ""}
        ${me ? tabLink("bookings", "我的预约", ["bookings", "booking", "book", "recovery"].includes(r.name)) : ""}
        ${me?.admin ? tabLink("review", "管理端", adminRoutes.has(r.name)) : ""}
      </nav><div class="account">
        ${me ? `<span class="avatar" aria-hidden="true">${esc(me.name.slice(0, 1).toUpperCase())}</span><span class="account-name">${esc(me.name)}</span>
          ${link("login", "切换账号", "secondary small")}<button class="btn ghost small" data-logout>退出</button>`
        : `${link("register", "注册", "ghost")}${link("login", "登录 / 演示账号", "")}`}
      </div></div></header>`;
  }

  function desk(area, current, content) {
    const admin = area === "admin";
    return `<div class="desk"><nav class="side" aria-label="${admin ? "管理端" : "卖家工作台"}">
      <h2>${admin ? "平台管理" : "卖家工作台"}</h2>
      ${(admin ? adminTabs : sellerTabs).map(([path, label]) => tabLink(path, label, path === current)).join("")}
    </nav><div>${content}</div></div>`;
  }

  const categoryTones = { "电子产品": "blue", "书籍": "violet", "生活用品": "teal", "运动用品": "gold" };

  function productTags(product) {
    return `<div class="product-tags">
      <span class="tag category-${categoryTones[product.category] || "neutral"}">${esc(product.category)}</span>
      <span class="tag condition">${esc(product.condition)}</span>
    </div>`;
  }

  function favoriteButton(product) {
    if (product.sellerID === snapshot.actor?.ID) return "";
    const saved = snapshot.favorites.includes(product.ID);
    return `<button type="button" class="favorite-button" data-favorite="${esc(product.ID)}"
      aria-pressed="${saved}" aria-label="收藏 ${esc(product.title)}" title="${saved ? "取消收藏" : "收藏商品"}">
      <span class="heart" aria-hidden="true">${saved ? "♥" : "♡"}</span>
    </button>`;
  }

  const interest = (product) => `<span class="interest" title="当前收藏该商品的账号数">关注量 <b>${product.followers}</b></span>`;

  function productCard(product, fromFavorites = false) {
    const path = "#" + esc(pathWith("product/" + product.ID, { from: fromFavorites ? "favorites" : "" }));
    return `<article class="product-card">
      <a class="card-link" href="${path}" aria-label="查看 ${esc(product.title)}">
        <div class="card-media">${image(product.photos[0], "")}</div>
        <div class="card-body">
          ${productTags(product)}
          <h3>${esc(product.title)}</h3>
          <p class="card-description">${esc(product.description)}</p>
          <small class="card-seller">卖家 · ${esc(person(product.sellerID))}</small>
          <div class="card-bottom"><span class="price">${money(product.cents)}</span>${interest(product)}</div>
        </div>
      </a>
      ${favoriteButton(product)}
    </article>`;
  }

  function market(r) {
    const values = Object.fromEntries(r.params);
    const q = (values.q || "").trim().toLowerCase();
    const category = values.category || "";
    const min = values.min ? D.parseMoney(values.min) : 0;
    const max = values.max ? D.parseMoney(values.max) : Infinity;
    const invalid = Number.isNaN(min) || Number.isNaN(max) || min > max;
    const products = snapshot.products.filter((product) => product.status === "PUBLISHED"
      && (!q || (product.title + " " + product.description).toLowerCase().includes(q))
      && (!category || product.category === category) && product.cents >= min && product.cents <= max);
    products.sort((a, b) => b.publishedAt - a.publishedAt || a.ID.localeCompare(b.ID));
    const page = pagination(products, r, "market");
    return `<section class="hero"><div class="hero-copy"><h1>${BRAND}</h1><p>挑选校园闲置，预约后和同学见面交付。</p></div>
      <div class="hero-mark" aria-hidden="true"><img src="${LOGO}" alt=""></div></section>
      <form class="panel filters" data-form="market">
        ${field("关键词", input("q", values.q, 'placeholder="输入商品关键词" maxlength="60"'))}
        ${field("分类", select("category", D.CATEGORIES, category, "全部分类"))}
        ${field("最低价（元）", input("min", values.min, 'inputmode="decimal" placeholder="不限"'))}
        ${field("最高价（元）", input("max", values.max, 'inputmode="decimal" placeholder="不限"'))}
        <div class="actions">${link("market", "重置")}${button("筛选商品")}</div>
        ${errorBox}</form>
      ${invalid ? notice("价格范围有误", "请输入合法价格，最低价不能高于最高价。", "danger") : ""}
      <div class="section-heading"><h2>可预约商品</h2><span class="muted">共 ${products.length} 件 · 新发布优先</span></div>
      ${page.items.length ? `<div class="cards">${page.items.map((product) => productCard(product)).join("")}</div>`
      : empty("没有匹配的商品", "试试更换关键词、分类或价格范围。", link("market", "查看全部商品"))}
      ${page.footer}`;
  }

  function favoritesPage(r) {
    const page = pagination(snapshot.favorites, r, "favorites");
    const rows = page.items.map((ID) => {
      const product = snapshot.products.find((item) => item.ID === ID && item.status === "PUBLISHED");
      if (product) return productCard(product, true);
      return `<article class="panel saved-unavailable">
        <div><h3>商品当前不可预约</h3><small>商品 ID · ${esc(ID)}</small></div>
        ${button("取消收藏", "secondary small", `type="button" data-favorite="${esc(ID)}" aria-pressed="true"`)}
      </article>`;
    });
    return heading("我的收藏", "", `<span class="muted">共 ${snapshot.favorites.length} 件</span>`)
      + (rows.length ? `<div class="cards">${rows.join("")}</div>${page.footer}`
        : empty("还没有收藏商品", "点击商品卡片右上角的爱心即可收藏。", link("market", "去逛集市", "")));
  }

  function productDetail(product, fromFavorites) {
    const back = fromFavorites ? "favorites" : "market";
    const backLabel = fromFavorites ? "返回我的收藏" : "返回集市";
    if (!product || product.status !== "PUBLISHED") {
      return heading("商品当前不可预约") + empty("商品状态已变化", "可在集市查看其他可预约商品。", link(back, backLabel, ""));
    }
    const self = product.sellerID === actorID;
    const action = self ? link("seller", "管理我的商品") : snapshot.actor ? link("book/" + product.ID, "预约商品", "")
      : link(pathWith("login", { next: "book/" + product.ID }), "登录后预约", "");
    return `${crumb(back, backLabel)}<div class="split">
      <section class="panel"><div data-gallery-main>${image(product.photos[0], product.title, "cover detail-photo")}</div>
      ${product.photos.length > 1 ? `<div class="gallery" aria-label="商品图片">
        ${product.photos.map((src, n) => `<button type="button" class="thumb" data-gallery="${n}" aria-label="查看第 ${n + 1} 张图片" aria-pressed="${n === 0}">${image(src, "")}</button>`).join("")}
      </div>` : ""}
      <div class="section-heading"><h2>商品描述</h2></div><p class="desc">${esc(product.description)}</p></section>
      <section class="panel detail-copy"><span class="chip good">可预约</span><h1>${esc(product.title)}</h1>
        <div class="detail-meta"><p class="price large">${money(product.cents)}</p>${interest(product)}</div>
        ${productTags(product)}<hr class="rule">
        ${pairs([["商品 ID", product.ID], ["卖家", person(product.sellerID)]])}
        <div class="actions">${action}${favoriteButton(product)}</div>
        ${notice("校园内见面交付", "交付时间和地点由买家在预约时提出。")}
      </section></div>`;
  }

  function demoButtons() {
    return D.SAMPLES.map((account) => `<button class="btn secondary small" type="button" data-demo="${account.ID}">${esc(account.role)} · ${account.name}</button>`).join("");
  }

  function authPage(register, next = "") {
    return `<div class="auth-layout">
      <div class="auth-side"><h2>校园二手交易</h2><p>登录后可以预约商品或发布闲置。</p><img src="assets/books.jpg" alt="可在集市交换的二手教材"></div>
      <section class="auth-form"><div class="form-stack">
        ${heading(register ? "创建普通账号" : "登录" + BRAND, register ? "请使用演示用的用户名和密码。" : "可使用下方演示账号体验不同角色。")}
        <form class="form-stack" data-form="${register ? "register" : "login"}" data-next="${esc(next)}">
          ${field("用户名", input("username", "", 'required maxlength="20" autocomplete="username"'), register ? "4–20 位字母、数字或下划线，忽略大小写判重。" : "")}
          ${field("密码", input("password", "", `type="password" required maxlength="64" autocomplete="${register ? "new-password" : "current-password"}"`), register ? "长度为 10–64 位。" : "")}
          ${register ? field("确认密码", input("confirm", "", 'type="password" required maxlength="64" autocomplete="new-password"')) : ""}
          ${errorBox}${button(register ? "创建账号" : "登录")}
        </form>
        <div class="actions spread"><a href="#market">‹ 继续浏览</a>
          <a href="#${esc(pathWith(register ? "login" : "register", { next }))}">${register ? "已有账号，去登录" : "没有账号，去注册"}</a></div>
        ${register ? "" : `<div class="account-demo" data-next="${esc(next)}"><p class="muted">点击任一角色直接登录演示。</p><div class="demo-accounts">${demoButtons()}</div></div>`}
      </div></section></div>`;
  }

  function commandButton(type, label, product, extra = {}, style = "secondary") {
    const payload = { cmd: type, product: product?.ID, version: product?.version, ...extra };
    const attributes = Object.entries(payload).filter(([, value]) => value != null)
      .map(([key, value]) => `data-${key}="${esc(value)}"`).join(" ");
    return button(label, style, 'type="button" ' + attributes);
  }

  function table(headers, rows) {
    return `<div class="table-wrap"><table><thead><tr>${headers.map((text) => `<th scope="col">${esc(text)}</th>`).join("")}
      </tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function myProducts(r) {
    const q = r.params.get("q") || "";
    const state = r.params.get("state") || "";
    const products = snapshot.products.filter((product) => product.sellerID === actorID
      && (!state || product.status === state) && product.title.toLowerCase().includes(q.toLowerCase()))
      .sort((a, b) => b.updatedAt - a.updatedAt);
    const page = pagination(products, r, "seller");
    const rows = page.items.map((product) => {
      let actions = "";
      if (D.editable(product)) actions = link("edit/" + product.ID, "编辑", "secondary small");
      if (product.status === "PENDING") actions = commandButton("withdraw", "撤回审核", product, {}, "secondary small");
      if (product.status === "PUBLISHED") actions = link("product/" + product.ID, "查看公开页", "ghost small")
        + commandButton("down", "下架", product, {}, "secondary small");
      if (product.status === "RESERVED") {
        const booking = snapshot.reservations.find((entry) => entry.productID === product.ID && D.active(entry));
        actions = (booking ? link("booking/" + booking.ID, "查看预约", "secondary small") : "")
          + '<span class="row-sub">有有效预约，请先处理预约再下架。</span>';
      }
      if (product.status === "SOLD") {
        const booking = snapshot.reservations.find((entry) => entry.productID === product.ID && entry.status === "COMPLETED");
        if (booking) actions = link("booking/" + booking.ID, "查看成交记录", "secondary small");
      }
      return `<tr><td><strong>${esc(titleOf(product))}</strong><span class="row-sub">${product.ID}</span>
        ${product.reason ? `<span class="row-sub">${esc(product.reason)}</span>` : ""}</td>
        <td>${statusChip("product", product.status)}</td><td>${money(product.cents)}</td><td>${stamp(product.updatedAt)}</td>
        <td><div class="actions">${actions || "—"}</div></td></tr>`;
    }).join("");
    return desk("seller", "seller", `${heading("我的商品", "查看自己的商品与审核状态。", link("edit/new", "＋ 发布商品", ""))}
      <form class="panel filters compact" data-form="query" data-path="seller">
        ${field("关键词", input("q", q, 'placeholder="搜索我的商品"'))}
        ${field("商品状态", select("state", D.PRODUCTS, state, "全部状态"))}
        <div class="actions">${button("查询")}${link("seller", "重置")}</div></form>
      ${rows ? `<section class="panel">${table(["商品 / ID", "状态", "价格", "最近更新", "操作"], rows)}</section>`
      : empty("没有符合条件的商品", "可以重置筛选或发布一件商品。", link("edit/new", "发布商品"))}${page.footer}`);
  }

  function photoTiles(photos) {
    return photos.map((src, index) => `<figure>${image(src, "商品图片 " + (index + 1))}
      <button type="button" class="btn ghost small" data-remove-photo="${index}" aria-label="移除第 ${index + 1} 张图片">移除</button></figure>`).join("");
  }

  function editPage(id) {
    const product = id === "new" ? null : snapshot.products.find((item) => item.ID === id && item.sellerID === actorID);
    if (id !== "new" && (!product || !D.editable(product))) {
      return desk("seller", "seller", empty("当前无法编辑此商品", "请从我的商品查看最新状态。", link("seller", "返回我的商品")));
    }
    editState = { photos: [...(product?.photos || [])] };
    return desk("seller", "seller", `${heading(product ? "编辑商品" : "发布商品", "可以先保存草稿，信息完整后再提交审核。")}
      <form class="split narrow" data-form="edit" data-product="${product?.ID || ""}" data-version="${product?.version || ""}">
        <section class="panel form-stack">
          <h2>商品信息</h2>
          ${field("商品标题", input("title", product?.title, 'maxlength="60"'), "最多 60 字，提交审核时必填。")}
          <div class="cols">${field("分类", select("category", D.CATEGORIES, product?.category, "请选择"))}
          ${field("成色", select("condition", D.CONDITIONS, product?.condition, "请选择"))}</div>
          ${field("价格（元）", input("price", product?.cents == null ? "" : (product.cents / 100).toFixed(2), 'inputmode="decimal" placeholder="例如 45.00"'), "¥0.01–¥100000.00，最多两位小数。")}
          ${field("商品描述", `<textarea name="description" maxlength="2000">${esc(product?.description)}</textarea>`, "最多 2000 字，提交审核时必填。")}
          ${errorBox}<div class="actions spread">${link("seller", "返回")}
            <div class="actions">${button("保存草稿", "secondary", 'name="intent" value="save"')}
            ${button("提交审核", "", 'name="intent" value="submit"')}</div></div>
        </section>
        <section class="panel stack"><h2>商品图片</h2>
          ${field("添加商品图片", '<input name="upload" type="file" accept="image/jpeg,image/png" multiple>', "可选。JPEG / PNG，最多 5 张，每张不超过 5 MB。")}
          <div class="uploaded" data-photos>${photoTiles(editState.photos)}</div>
          <p class="muted" data-photo-count>${editState.photos.length} / 5 张</p></section>
      </form>`);
  }

  function bookingForm(id) {
    const product = snapshot.products.find((item) => item.ID === id);
    if (!product || product.status !== "PUBLISHED" || product.sellerID === actorID) {
      const reason = product?.sellerID === actorID ? "不能预约自己发布的商品。" : "商品已被预约或已下架。";
      return heading("商品当前不可预约") + empty("请查看最新商品状态", reason, link("market", "返回集市", ""));
    }
    const now = Date.now();
    const formDate = D.dateInput(now + D.DAY);
    return `${crumb("product/" + id, "返回商品")}${heading("提交预约", "提出交付时间和校园公共地点，等卖家确认后按约见面。")}
      <div class="split narrow">
      <form class="panel form-stack" data-form="book" data-product="${product.ID}" data-version="${product.version}">
        <h2>填写交付约定</h2>
        ${field("交付时间（北京时间）", input("appointment", formDate,
          `type="datetime-local" required min="${D.dateInput(now + 60000)}" max="${D.dateInput(now + 30 * D.DAY)}"`), "需晚于提交时间，并在未来 30 天内。")}
        ${field("交付地点", input("place", "", 'required minlength="2" maxlength="100" placeholder="例如 仙林校区图书馆正门外"'),
          "2–100 字，请勿填写宿舍房号或身份证号。")}
        ${notice("交付信息的查看范围", "仅本单双方和获授权管理员可查看。")}
        <details class="account-demo"><summary>演示响应丢失</summary><label class="check-line"><input type="checkbox" name="lost">模拟提交成功后未收到响应</label></details>
        ${errorBox}<div class="actions end">${link("product/" + product.ID, "返回商品")}${button("提交预约")}</div>
      </form>
      <aside class="panel stack"><h2>预约商品</h2>${image(product.photos[0], product.title)}
        <h3>${esc(product.title)}</h3>${productTags(product)}
        <div class="detail-meta"><span class="price"><small>预约时价格</small> ${money(product.cents)}</span>${interest(product)}</div>
        ${pairs([["商品 ID", product.ID], ["卖家", person(product.sellerID)]])}
        <p class="desc">${esc(product.description)}</p>
        <p class="muted">预约建立后会占用这件商品。双方线下见面交付。</p></aside></div>`;
  }

  function bookings(r, admin = false) {
    const seller = !admin && r.params.get("role") === "seller";
    const state = r.params.get("state") || "";
    const path = admin ? "admin-bookings" : "bookings";
    const entries = snapshot.reservations.filter((entry) => (admin || (seller ? entry.sellerID === actorID : entry.buyerID === actorID))
      && (!state || entry.status === state)).sort((a, b) => b.createdAt - a.createdAt);
    const page = pagination(entries, r, path);
    const rows = page.items.map((entry) => `<tr>
      <td><strong>${esc(entry.title)}</strong><span class="row-sub">${entry.ID} · ${entry.productID}</span></td>
      <td>${statusChip("booking", entry.status)}</td><td>${money(entry.cents)}</td>
      <td>${esc(person(seller ? entry.buyerID : entry.sellerID))}</td><td>${stamp(entry.createdAt)}</td>
      <td>${link("booking/" + entry.ID, "查看详情", "secondary small")}</td></tr>`).join("");
    const content = `${heading(admin ? "平台预约" : "我的预约", admin ? "查看平台预约状态和交付详情。" : "查看本人发起或收到的预约。")}
      ${pending[actorID] && !admin ? `<div class="panel actions spread"><span>有一条提交等待查询结果。</span>${link("recovery", "查询本次结果", "")}</div>` : ""}
      ${admin ? "" : `<nav class="subtabs" aria-label="预约角色">
        ${tabLink("bookings", "我发起的预约", !seller)}${tabLink("bookings?role=seller", "我收到的预约", seller)}
      </nav>`}
      <form class="panel filters compact" data-form="query" data-path="${path}">
        ${seller ? '<input type="hidden" name="role" value="seller">' : ""}
        ${field("预约状态", select("state", D.BOOKINGS, state, "全部状态"))}<div class="actions">${button("查询")}</div>
      </form>
      ${rows ? `<section class="panel">${table(["商品 / 预约 ID", "状态", "预约时价格", seller ? "买家" : "卖家", "创建时间", "操作"], rows)}</section>`
      : empty("暂无符合条件的预约", "新的预约或历史预约会显示在这里。", link("market", "逛集市"))}
      ${page.footer}`;
    return admin ? desk("admin", path, content) : seller ? desk("seller", "bookings?role=seller", content) : content;
  }

  function bookingDetail(id) {
    const record = service.bookingDetail(actorID, id);
    const product = record.product;
    const seller = record.sellerID === actorID;
    const buyer = record.buyerID === actorID;
    const personal = seller || buyer;
    const access = delivery?.actorID === actorID && delivery?.ID === id ? delivery : null;
    const visible = record.privateVisible || access;
    const details = record.privateVisible ? record : access;
    const payload = { reservation: id };
    let actions = "";
    if (seller && record.status === "PENDING") {
      actions = commandButton("accept", "接受预约", product, payload, "")
        + commandButton("reject", "拒绝预约", product, { ...payload, reason: "required" }, "danger");
    }
    if (buyer && record.status === "PENDING") actions = commandButton("cancel", "取消预约", product, payload);
    if (personal && record.status === "ACCEPTED") {
      actions = commandButton("cancel", "取消预约", product, { ...payload, reason: "required" });
      if (buyer) {
        actions = `<form class="form-stack" data-form="complete" data-reservation="${id}" data-version="${product.version}">
          <label class="check-line"><input type="checkbox" name="received" required>我已收到实物</label>
          ${errorBox}${button("确认交付完成")}</form>` + actions;
      }
    }
    const progress = [
      ["预约已提交", record.createdAt],
      ...(record.confirmedAt ? [["卖家已确认", record.confirmedAt]] : []),
      ...(record.closedAt ? [[D.BOOKINGS[record.status], record.closedAt]] : [])
    ];
    const back = !personal ? "admin-bookings" : seller ? "bookings?role=seller" : "bookings";
    const content = `${crumb(back, !personal ? "平台预约" : "我的预约")}
      ${heading("预约 " + record.ID, "所有时间按北京时间显示。", statusChip("booking", record.status))}
      <div class="split narrow">
        <section class="panel stack"><h2>交易信息</h2>
          <div class="item-line">${product.photos[0] ? image(product.photos[0], "") : ""}
            <div><h3>${esc(record.title)}</h3><small>${product.ID}</small></div></div>
          ${pairs([["预约时价格", money(record.cents)], ["买家", person(record.buyerID)], ["卖家", person(record.sellerID)],
            ["商品状态", D.PRODUCTS[product.status]], ...(record.status === "PENDING" ? [["确认截止", stamp(record.deadline)]] : [])])}
          <hr class="rule"><h2>交付约定</h2>
          ${visible ? pairs([["交付时间", stamp(details.appointmentAt)], ["交付地点", details.place]])
            : `<p class="muted">查看交付信息会写入操作记录。</p>
              <div>${button("查看交付信息", "secondary", 'type="button" data-private="' + id + '"')}</div>`}
          <hr class="rule"><h2>预约进度</h2>
          <ol class="timeline">${progress.map(([label, time]) => `<li><strong>${esc(label)}</strong><small>${stamp(time)}</small></li>`).join("")}</ol>
        </section>
        <aside class="panel stack"><h2>${record.status === "COMPLETED" ? "已记录交付完成" : "预约处理"}</h2>
          ${record.status === "PENDING" ? notice("等待卖家处理", "卖家可在确认截止前接受或拒绝。双方保留原交付约定。") : ""}
          ${record.status === "ACCEPTED" ? notice("按约见面交付", "收到实物后，由买家确认完成。已确认的预约取消时需要填写原因。") : ""}
          ${record.status === "COMPLETED" ? notice("交易已完成", "首次完成时间为 " + stamp(record.completedAt) + "，商品已售出。", "good") : ""}
          ${record.reason ? notice(D.BOOKINGS[record.status], record.reason, "warn") : ""}
          ${actions ? `<div class="stack">${actions}</div>` : link(back, "返回预约列表")}
        </aside>
      </div>`;
    return personal ? content : desk("admin", "admin-bookings", content);
  }

  function recoveryPage() {
    const request = pending[actorID];
    if (!request) return heading("预约结果查询") + empty("没有待查询的提交", "可在我的预约查看已有结果。", link("bookings", "我的预约"));
    return `<section class="panel recovery stack">
      ${heading("预约结果待确认", "这次提交未收到响应。可以查询已保存的结果和当前状态。")}
      ${pairs([["商品 ID", request.productID]])}
      <div class="actions">${button("查询本次结果", "", 'type="button" data-recover')}${link("bookings", "我的预约")}</div>
    </section>`;
  }

  function review(r) {
    const products = snapshot.products.filter((product) => product.status === "PENDING" && product.review)
      .sort((a, b) => b.review.at - a.review.at);
    const page = pagination(products, r, "review");
    const current = r.id ? products.find((item) => item.ID === r.id) : page.items[0];
    const list = page.items.map((product) => `<li>
      <a href="#review/${product.ID}"${current?.ID === product.ID ? ' aria-current="page"' : ""}>
      <strong>${esc(titleOf(product))}</strong><small class="row-sub">${product.ID} · ${esc(person(product.sellerID))}</small></a></li>`).join("");
    const view = current ? current.review.content : null;
    return desk("admin", "review", `${heading("商品审核", "按本次送审内容作出审核决定。")}
      ${list ? `<div class="split narrow">
        <section class="panel stack"><h2>审核提交 ${esc(current?.review.ID || "")}</h2>
          ${current ? `<div class="item-line">${view.photos[0] ? image(view.photos[0], "") : ""}<div><h3>${esc(view.title)}</h3>
            <small>${current.ID} · ${stamp(current.review.at)} 提交</small></div></div>
            ${pairs([["分类与成色", view.category + " · " + view.condition], ["价格", money(view.cents)]])}
            <p class="desc">${esc(view.description)}</p>
            <div class="actions end">${commandButton("rejectReview", "驳回", current, { review: current.review.ID, reason: "required" }, "danger")}
            ${commandButton("approve", "通过审核", current, { review: current.review.ID }, "")}</div>`
            : notice("送审状态已更新", "请从待审核列表选择最新提交。", "warn")}
        </section>
        <aside class="panel stack"><h2>待审核列表 · ${products.length} 条</h2><ul class="review-list">${list}</ul></aside>
      </div>${page.footer}` : empty("没有待审核商品", "卖家提交审核后会出现在这里。")}`);
  }

  function moderation(r) {
    const q = (r.params.get("q") || "").toLowerCase();
    const state = r.params.get("state") || "";
    const products = snapshot.products.filter((product) => (!state || product.status === state)
      && (!q || (product.ID + " " + product.title).toLowerCase().includes(q))).sort((a, b) => b.updatedAt - a.updatedAt);
    const page = pagination(products, r, "moderation");
    const rows = page.items.map((product) => {
      const active = snapshot.reservations.find((item) => item.productID === product.ID && D.active(item));
      const action = D.bannable(product)
        ? commandButton("ban", active ? "封禁并取消预约" : "封禁", product, { reason: "required", impact: active?.ID }, "danger small")
        : product.status === "SOLD" ? commandButton("mark", "追加违规标记", product, { reason: "required" }, "secondary small") : "—";
      return `<tr><td><strong>${esc(titleOf(product))}</strong><small class="row-sub">${product.ID} · ${esc(person(product.sellerID))}</small>
        ${product.reason ? `<small class="row-sub">${esc(product.reason)}</small>` : ""}
        ${product.marks.length ? `<small class="row-sub">最新违规标记 · ${esc(product.marks.at(-1).reason)}</small>` : ""}</td>
        <td>${statusChip("product", product.status)}</td><td>${active ? `<a href="#booking/${active.ID}">${active.ID}</a>` : "—"}</td>
        <td><div class="actions">${action}</div></td></tr>`;
    }).join("");
    return desk("admin", "moderation", `${heading("违规处置", "按商品当前状态封禁或追加违规标记。")}
      <form class="panel filters compact" data-form="query" data-path="moderation">
        ${field("商品 ID 或关键词", input("q", r.params.get("q"), 'placeholder="搜索商品"'))}
        ${field("商品状态", select("state", D.PRODUCTS, state, "全部状态"))}<div class="actions">${button("查询")}</div></form>
      ${rows ? `<section class="panel">${table(["商品 / 卖家", "状态", "有效预约", "处置"], rows)}</section>`
      : empty("没有符合条件的商品", "可以换一个关键词或状态。")}${page.footer}`);
  }

  function manageAccounts(r) {
    const q = (r.params.get("q") || "").toLowerCase();
    const count = snapshot.accounts.filter((item) => item.admin).length;
    const rows = snapshot.accounts.filter((item) => item.name.toLowerCase().includes(q)).map((item) => {
      const last = item.admin && count <= 1;
      return `<tr><td><strong>${esc(item.name)}</strong><small class="row-sub">${item.ID}</small></td>
        <td><span class="chip ${item.admin ? "accent" : ""}">${item.admin ? "管理员" : "普通账号"}</span></td>
        <td>${last ? button("撤销管理权限", "small", "disabled") + '<small class="row-sub">最后一名有效管理员</small>'
          : commandButton(item.admin ? "revoke" : "grant", item.admin ? "撤销管理权限" : "授予管理权限", null,
            { account: item.ID, username: item.name }, "secondary small")}</td></tr>`;
    }).join("");
    return desk("admin", "admin-accounts", `${heading("权限管理", "当前有效管理员 " + count + " 人。")}
      <form class="panel filters compact" data-form="query" data-path="admin-accounts">
        ${field("用户名", input("q", r.params.get("q"), 'placeholder="按用户名查询"'))}<div class="actions">${button("查询")}</div>
      </form>${rows ? `<section class="panel">${table(["账号 / ID", "当前权限", "操作"], rows)}</section>`
      : empty("没有符合条件的账号", "检查用户名或清空筛选。")}`);
  }

  function logs(r, admin = false) {
    const p = Object.fromEntries(r.params);
    const path = admin ? "admin-logs" : "logs";
    const start = p.start ? D.readDate(p.start) : -Infinity;
    const end = p.end ? D.readDate(p.end, true) : Infinity;
    const rows = snapshot.logs.filter((item) => (admin || item.scope.includes(actorID))
      && (!p.target || item.objectID.toLowerCase().includes(p.target.toLowerCase()))
      && (!p.actor || person(item.actorID).toLowerCase().includes(p.actor.toLowerCase()))
      && (!p.type || item.type === p.type) && (!p.outcome || item.outcome === p.outcome)
      && item.at >= start && item.at < end).sort((a, b) => b.at - a.at).map((item) => `<tr>
        <td>${stamp(item.at)}</td><td>${esc(person(item.actorID))}</td><td>${esc(item.objectID)}</td>
        <td>${esc(D.ACTIONS[item.type])}</td><td><span class="chip ${item.outcome === "失败" ? "danger" : item.outcome === "成功" ? "good" : "info"}">${esc(item.outcome)}</span></td>
        <td>${esc(item.before || "—")} → ${esc(item.after || "—")}${item.reason ? `<small class="row-sub">${esc(item.reason)}</small>` : ""}</td>
      </tr>`).join("");
    return desk(admin ? "admin" : "seller", path, `${heading(admin ? "平台操作记录" : "我的操作记录", admin ? "查询平台业务操作和交付信息访问记录。" : "查询本人参与的交易及相关操作。")}
      <form class="panel filters compact" data-form="query" data-path="${path}">
        ${field("对象 ID", input("target", p.target, 'placeholder="例如 R-0434"'))}
        ${field("操作人", input("actor", p.actor, 'placeholder="全部操作人"'))}
        ${field("动作", select("type", D.ACTIONS, p.type, "全部动作"))}
        ${field("结果", select("outcome", ["成功", "失败", "访问成功"], p.outcome, "全部结果"))}
        ${field("起始日期", input("start", p.start, 'type="date"'))}
        ${field("结束日期", input("end", p.end, 'type="date"'))}
        <div class="actions">${button("查询")}${link(path, "重置")}</div>${errorBox}
      </form>
      ${rows ? `<section class="panel">${table(["时间（北京时间）", "操作人", "对象 ID", "动作", "结果", "状态变化 / 原因"], rows)}</section>`
      : empty("没有匹配的操作记录", "可以调整对象、动作、结果或时间范围。")}`);
  }

  function stats(r, admin = false) {
    const path = admin ? "admin-stats" : "stats";
    const startValue = r.params.get("start") || D.shortDate(Date.now() - 7 * D.DAY);
    const endValue = r.params.get("end") || D.shortDate(Date.now() + D.DAY);
    const start = D.readDate(startValue);
    const end = D.readDate(endValue);
    const done = snapshot.reservations.filter((entry) => (admin || entry.sellerID === actorID)
      && entry.status === "COMPLETED" && entry.completedAt >= start && entry.completedAt < end);
    const products = snapshot.products.filter((product) => admin || product.sellerID === actorID);
    const amount = done.reduce((sum, item) => sum + item.cents, 0);
    const states = Object.entries(D.PRODUCTS).map(([state, label]) => {
      const count = products.filter((product) => product.status === state).length;
      return `<div class="status-row"><span>${label}</span><span class="bar" aria-hidden="true"><i style="width:${products.length ? count / products.length * 100 : 0}%"></i></span><span>${count} 件</span></div>`;
    }).join("");
    const daily = new Map();
    for (const item of done) {
      const date = D.shortDate(item.completedAt);
      daily.set(date, (daily.get(date) || 0) + 1);
    }
    const max = Math.max(1, ...daily.values());
    const trend = [...daily.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([date, count]) => `<div class="status-row">
      <span>${date.slice(5)}</span><span class="bar" aria-hidden="true"><i style="width:${count / max * 100}%"></i></span><span>${count} 笔</span></div>`).join("");
    return desk(admin ? "admin" : "seller", path, `${heading("交易统计", admin ? "统计全平台商品与已完成交易。" : "统计本人商品与已完成交易。")}
      <form class="panel filters compact" data-form="query" data-path="${path}">
        ${field("起始日期", input("start", startValue, 'type="date" required'))}
        ${field("结束日期", input("end", endValue, 'type="date" required'))}
        <div class="actions">${button("应用区间")}<small>北京时间 · 含起点，不含终点</small></div>${errorBox}
      </form>
      <div class="stack"><div class="metrics">
        <section class="panel"><h3>成交笔数</h3><strong class="metric-number">${done.length} 笔</strong><small>按首次完成时间计入</small></section>
        <section class="panel"><h3>约定总额</h3><strong class="metric-number">${money(amount)}</strong><small>按创建预约时的约定价格汇总</small></section>
        <section class="panel"><h3>当前商品</h3><strong class="metric-number">${products.length} 件</strong><small>按当前状态统计，与日期区间独立</small></section>
      </div><div class="split narrow"><section class="panel"><h2>区间内成交</h2>
      ${trend || '<p class="caption">该时间段没有已完成交易。</p>'}</section><section class="panel"><h2>当前商品状态</h2>${states}</section></div></div>`);
  }

  let conflict;

  function page(r) {
    if (r.name === "market") return market(r);
    if (r.name === "product") return productDetail(snapshot.products.find((product) => product.ID === r.id), r.params.get("from") === "favorites");
    if (r.name === "login") return authPage(false, r.params.get("next") || "");
    if (r.name === "register") return authPage(true, r.params.get("next") || "");
    if (!snapshot.actor) return authPage(false, r.full);
    if (adminRoutes.has(r.name) && !snapshot.actor.admin) {
      return heading("需要管理权限") + empty("当前账号无法访问管理端", "可以切换到获授权的演示管理员账号。", link("login", "切换账号"));
    }
    switch (r.name) {
      case "favorites": return favoritesPage(r);
      case "seller": return myProducts(r);
      case "edit": return editPage(r.id);
      case "book": return bookingForm(r.id);
      case "bookings": return bookings(r);
      case "booking": return bookingDetail(r.id);
      case "recovery": return recoveryPage();
      case "conflict":
        return `<section class="panel recovery stack">${heading(conflict?.code === "occupied" ? "商品已被预约" : "商品状态已变化",
          conflict?.message || "请重新查看商品的当前状态。")}
          <div class="actions">${link("market", "返回集市", "")}${conflict ? link("product/" + conflict.productID, "刷新商品状态") : ""}</div>
        </section>`;
      case "review": return review(r);
      case "moderation": return moderation(r);
      case "admin-bookings": return bookings(r, true);
      case "admin-accounts": return manageAccounts(r);
      case "logs": return logs(r);
      case "admin-logs": return logs(r, true);
      case "stats": return stats(r);
      case "admin-stats": return stats(r, true);
      default: return empty("找不到此页面", "可以返回集市继续浏览。", link("market", "返回集市", ""));
    }
  }

  function render() {
    const r = route();
    let content;
    try {
      service.expire();
      snapshot = service.snapshot(actorID);
      if (!snapshot.actor && actorID) {
        actorID = null;
        sessionWrite(SESSION, null);
      }
      content = page(r);
    } catch (error) {
      if (!(error instanceof D.DemoError)) console.error(error);
      snapshot ||= service.snapshot(null);
      content = `<div class="section-heading"></div>${empty("当前页面无法显示",
        error instanceof D.DemoError ? error.message : "请刷新页面后再试。", link("market", "返回集市", ""))}`;
    }
    site.innerHTML = `${header(r)}<main class="wrap" id="content" tabindex="-1">${content}
      <footer class="footer"><small>${BRAND} · 本地演示 · ${service.persistent ? "数据保存在当前浏览器" : "数据保存在当前窗口"}</small>
      <button class="btn ghost small" type="button" data-reset>重置演示数据</button></footer>
    </main>`;
    const h1 = site.querySelector("h1");
    document.title = h1 && h1.textContent !== BRAND ? h1.textContent + " · " + BRAND : BRAND;
  }

  function showToast(message) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.hidden = false;
    toastTimer = setTimeout(() => { toast.hidden = true; }, 4200);
  }

  function showError(form, error) {
    const box = form.querySelector("[data-error]");
    const message = error instanceof D.DemoError ? error.message : "操作未完成，请重试。";
    if (!(error instanceof D.DemoError)) console.error(error);
    if (!box) {
      showToast(message);
      return;
    }
    box.textContent = message;
    box.hidden = false;
    box.tabIndex = -1;
    box.focus();
    if (["stale", "expired", "occupied", "unavailable"].includes(error.code)) {
      const refresh = document.createElement("button");
      refresh.type = "button";
      refresh.className = "btn secondary small";
      refresh.dataset.refresh = "true";
      refresh.textContent = "刷新当前状态";
      box.append(" ", refresh);
    }
  }

  function token() {
    return globalThis.crypto?.randomUUID?.() || String(Date.now()) + "-" + Math.random().toString(36).slice(2);
  }

  function signedIn(account, requested = "") {
    actorID = account.ID;
    sessionWrite(SESSION, actorID);
    delivery = null;
    const permitted = /^(market|product|book|bookings|booking|favorites|seller|edit|review|moderation|admin-[a-z-]+|logs|stats|recovery)([/?]|$)/.test(requested);
    const home = account.admin ? "review" : account.name === "lin_seller" ? "seller" : "market";
    go(permitted ? requested : home);
    showToast("已登录 " + account.name);
  }

  function handleSearch(kind, form, values) {
    if (kind === "market") {
      const min = values.min ? D.parseMoney(values.min) : 0;
      const max = values.max ? D.parseMoney(values.max) : Infinity;
      if (Number.isNaN(min) || Number.isNaN(max)) throw new D.DemoError("input", "请输入合法价格，最多两位小数。");
      if (min > max) throw new D.DemoError("input", "最低价不能高于最高价。");
      go(pathWith("market", values));
      return;
    }
    if (values.start && values.end) {
      const statsPage = ["stats", "admin-stats"].includes(form.dataset.path);
      const start = D.readDate(values.start);
      const end = D.readDate(values.end, !statsPage);
      if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) {
        throw new D.DemoError("input", statsPage ? "结束日期需晚于起始日期。" : "请输入有效的日期范围。");
      }
    }
    go(pathWith(form.dataset.path, values));
  }

  async function submitForm(form, submitter) {
    const kind = form.dataset.form;
    const fields = Object.fromEntries(new FormData(form));
    if (kind === "login") {
      const account = await service.login(fields.username, fields.password);
      signedIn(account, form.dataset.next);
    } else if (kind === "register") {
      if (fields.password !== fields.confirm) throw new D.DemoError("input", "两次输入的密码不一致。");
      const account = await service.register(fields.username, fields.password);
      signedIn(account, form.dataset.next);
      showToast("账号已创建。");
    } else if (kind === "market" || kind === "query") {
      handleSearch(kind, form, Object.fromEntries(Object.entries(fields).map(([name, value]) => [name, String(value).trim()])));
    } else if (kind === "edit") {
      const { title, category, condition, price, description } = fields;
      const type = submitter?.value === "submit" ? "submit" : "save";
      service.command(actorID, { type, productID: form.dataset.product || null, version: form.dataset.version,
        fields: { title, category, condition, price, description, photos: editState.photos } });
      go("seller");
      showToast(type === "submit" ? "商品已提交审核。" : "草稿已保存。");
    } else if (kind === "book") {
      if (pending[actorID]) throw new D.DemoError("input", "请先在我的预约中查询上一次提交结果。");
      const command = { type: "book", productID: form.dataset.product, version: form.dataset.version,
        appointment: fields.appointment, place: fields.place.trim(), token: token() };
      let result;
      try {
        result = service.command(actorID, command);
      } catch (error) {
        if (!["occupied", "stale", "unavailable"].includes(error.code)) throw error;
        conflict = { code: error.code, message: error.message, productID: command.productID };
        go("conflict");
        return;
      }
      if (fields.lost) {
        pending[actorID] = command;
        sessionWrite(PENDING, JSON.stringify(pending));
        go("recovery");
      } else {
        go("booking/" + result.reservationID);
        showToast("预约已提交，等待卖家确认。");
      }
    } else if (kind === "complete") {
      const result = service.command(actorID, { type: "complete", reservationID: form.dataset.reservation,
        version: form.dataset.version, received: fields.received === "on", token: token() });
      go("booking/" + result.reservationID);
      showToast("已记录交付完成。");
    }
  }

  site.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form.matches("[data-form]")) return;
    event.preventDefault();
    const submitter = event.submitter;
    if (submitter?.disabled) return;
    if (submitter) submitter.disabled = true;
    try { await submitForm(form, submitter); }
    catch (error) { showError(form, error); }
    finally { if (submitter?.isConnected) submitter.disabled = false; }
  });

  const confirmations = {
    withdraw: "撤回后商品回到草稿，可以继续编辑。",
    approve: "通过后，本次送审商品会在集市公开。",
    rejectReview: "驳回后，卖家可以查看原因并修改重提。",
    down: "下架后商品退出公开列表，再发布需重新审核。",
    ban: "确认后商品保持封禁。",
    mark: "追加标记后保留成交状态和历史记录。",
    accept: "接受后保留买家提出的时间和地点，商品继续占用。",
    reject: "拒绝后结束该预约并释放商品。",
    cancel: "取消后保留预约记录，并释放商品。",
    grant: "授予后，该账号可访问管理端。",
    revoke: "撤销后，该账号失去管理端访问权限。"
  };

  function openCommand(element) {
    const { cmd, product, version, reservation, review, account, username, reason, impact } = element.dataset;
    const command = { type: cmd, productID: product, version, reservationID: reservation, reviewID: review, accountID: account, token: token() };
    dialogAction = { command, path: route().full };
    const message = cmd === "ban" && impact ? "封禁会同步取消预约 " + impact + "，双方可查看平台原因。"
      : (username ? "账号 " + username + "。 " : "") + confirmations[cmd];
    const destructive = ["ban", "reject", "rejectReview", "revoke"].includes(cmd);
    dialog.innerHTML = `<form class="form-stack" data-dialog-form><div><h2 id="dialog-title">${esc(D.ACTIONS[cmd])}</h2>
      <p class="muted">${esc(message)}</p></div>
      ${reason === "required" ? field("原因", reasonText()) : ""}${errorBox}<div class="actions end">
      ${button("返回", "secondary", 'type="button" data-close-dialog')}${button("确认" + D.ACTIONS[cmd], destructive ? "danger" : "")}</div></form>`;
    dialog.showModal();
  }

  function openReset() {
    dialogAction = { reset: true };
    dialog.innerHTML = `<form class="form-stack" data-dialog-form><div><h2 id="dialog-title">重置演示数据</h2>
      <p class="muted">恢复初始演示数据。此浏览器里新建的演示账号、商品、预约和收藏将被清除。</p></div>
      ${errorBox}<div class="actions end">${button("返回", "secondary", 'type="button" data-close-dialog')}
      ${button("确认重置", "danger")}</div></form>`;
    dialog.showModal();
  }

  dialog.addEventListener("click", (event) => {
    if (event.target.closest("[data-close-dialog]")) dialog.close();
    if (event.target.closest("[data-refresh]")) { dialog.close(); render(); }
  });
  dialog.addEventListener("submit", (event) => {
    const form = event.target;
    if (!form.matches("[data-dialog-form]")) return;
    event.preventDefault();
    if (!dialogAction) return;
    try {
      if (dialogAction.reset) {
        service.reset();
        actorID = null;
        delivery = null;
        pending = {};
        sessionWrite(SESSION, null);
        sessionWrite(PENDING, null);
        dialog.close();
        go("market");
        showToast("已恢复初始演示数据。");
        return;
      }
      const { command, path } = dialogAction;
      const reason = new FormData(form).get("reason");
      const result = service.command(actorID, { ...command, reason });
      dialog.close();
      if (["approve", "rejectReview"].includes(command.type)) go("review");
      else if (["accept", "reject", "cancel"].includes(command.type)) go("booking/" + result.reservationID);
      else go(path);
      showToast(D.ACTIONS[command.type] + "已保存。");
    } catch (error) { showError(form, error); }
  });

  function updatePhotos(form) {
    form.querySelector("[data-photos]").innerHTML = photoTiles(editState.photos);
    form.querySelector("[data-photo-count]").textContent = editState.photos.length + " / 5 张";
  }

  async function localPreview(file) {
    if (!["image/jpeg", "image/png"].includes(file.type) || file.size > 5 * 1024 * 1024) {
      throw new D.DemoError("input", "只接受 JPEG 或 PNG 图片，每张不超过 5 MB。");
    }
    let photo;
    try { photo = await createImageBitmap(file); }
    catch { throw new D.DemoError("input", "图片无法读取，请选择有效的 JPEG 或 PNG 文件。"); }
    try {
      const scale = Math.min(1, 960 / Math.max(photo.width, photo.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(photo.width * scale));
      canvas.height = Math.max(1, Math.round(photo.height * scale));
      const context = canvas.getContext("2d");
      context.fillStyle = "#fff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(photo, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL("image/jpeg", .77);
    } finally { photo.close(); }
  }

  site.addEventListener("change", async (event) => {
    const picker = event.target;
    if (!picker.matches('input[name="upload"]')) return;
    const form = picker.form;
    const state = editState;
    const files = Array.from(picker.files);
    if (!files.length) return;
    const buttons = form.querySelectorAll('button[name="intent"]');
    buttons.forEach((item) => { item.disabled = true; });
    picker.disabled = true;
    try {
      if (state.photos.length + files.length > 5) throw new D.DemoError("input", "商品图片最多 5 张，请先移除部分图片。");
      const previews = await Promise.all(files.map(localPreview));
      if (state !== editState || !form.isConnected) return;
      state.photos.push(...previews);
      updatePhotos(form);
      form.querySelector("[data-error]").hidden = true;
    } catch (error) {
      if (form.isConnected) showError(form, error);
    } finally {
      picker.value = "";
      picker.disabled = false;
      buttons.forEach((item) => { item.disabled = false; });
    }
  });

  site.addEventListener("click", async (event) => {
    const anchor = event.target.closest('a[href^="#"]');
    if (anchor && anchor.hash === window.location.hash && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      render();
      return;
    }
    const element = event.target.closest("button");
    if (!element || element.disabled) return;
    try {
      if (element.hasAttribute("data-logout")) {
        actorID = null;
        delivery = null;
        sessionWrite(SESSION, null);
        go("market");
        showToast("已退出登录。");
      } else if (element.dataset.demo) {
        const account = D.SAMPLES.find((item) => item.ID === element.dataset.demo);
        const next = element.closest("[data-next]")?.dataset.next;
        element.disabled = true;
        try { signedIn(await service.login(account.name, D.DEMO_PASSWORD), next); }
        finally { if (element.isConnected) element.disabled = false; }
      } else if (element.dataset.favorite) {
        if (!snapshot.actor) {
          go(pathWith("login", { next: route().full }));
          showToast("登录后可以收藏商品。");
          return;
        }
        const productID = element.dataset.favorite;
        const saved = element.getAttribute("aria-pressed") !== "true";
        const hadFocus = element === document.activeElement;
        service.setFavorite(actorID, productID, saved);
        render();
        if (hadFocus) {
          const buttons = [...site.querySelectorAll("[data-favorite]")];
          const next = buttons.find((item) => item.dataset.favorite === productID) || buttons[0] || site.querySelector("main");
          next.focus({ preventScroll: true });
        }
        showToast(saved ? "已加入我的收藏。" : "已取消收藏。");
      } else if (element.dataset.cmd) {
        openCommand(element);
      } else if (element.dataset.private) {
        const detail = service.bookingDetail(actorID, element.dataset.private, true);
        delivery = { actorID, ID: detail.ID, appointmentAt: detail.appointmentAt, place: detail.place };
        render();
        showToast("已记录交付信息访问。");
      } else if (element.hasAttribute("data-recover")) {
        const request = pending[actorID];
        if (!request) { go("bookings"); return; }
        const result = service.command(actorID, request);
        delete pending[actorID];
        sessionWrite(PENDING, JSON.stringify(pending));
        go("booking/" + result.reservationID);
        showToast("已恢复原提交结果。");
      } else if (element.hasAttribute("data-reset")) {
        openReset();
      } else if (element.hasAttribute("data-refresh")) {
        render();
      } else if (element.dataset.gallery != null) {
        const product = snapshot.products.find((item) => item.ID === route().id);
        const index = Number(element.dataset.gallery);
        if (!product?.photos[index]) return;
        site.querySelector("[data-gallery-main]").innerHTML = image(product.photos[index], product.title, "cover detail-photo");
        site.querySelectorAll("[data-gallery]").forEach((item) => item.setAttribute("aria-pressed", String(item === element)));
      } else if (element.dataset.removePhoto != null) {
        const form = element.closest("[data-form=edit]");
        if (!form || !editState) return;
        editState.photos.splice(Number(element.dataset.removePhoto), 1);
        updatePhotos(form);
        form.querySelector("[data-error]").hidden = true;
      }
    } catch (error) {
      if (!(error instanceof D.DemoError)) console.error(error);
      showToast(error instanceof D.DemoError ? error.message : "操作未完成，请重试。");
    }
  });

  document.querySelector("[data-skip]").addEventListener("click", (event) => {
    event.preventDefault();
    site.querySelector("main")?.focus();
  });
  window.addEventListener("hashchange", () => {
    if (dialog.open) dialog.close();
    render();
    window.scrollTo(0, 0);
  });
  window.setInterval(() => {
    try {
      if (service.expire() && !dialog.open && ["market", "product", "favorites", "seller", "bookings", "booking", "admin-bookings"].includes(route().name)) render();
    } catch (error) {
      showToast(error instanceof D.DemoError ? error.message : "当前无法更新演示数据。");
    }
  }, 30000);

  render();
}());
