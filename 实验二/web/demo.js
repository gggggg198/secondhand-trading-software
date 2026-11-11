(function () {
  "use strict";

  const DAY = 24 * 60 * 60 * 1000;
  const BEIJING = 8 * 60 * 60 * 1000;
  const DATABASE = "nju-market-demo-v1";
  const DEMO_PASSWORD = "CampusDemo2026";
  const CATEGORIES = ["书籍", "电子产品", "生活用品", "运动用品", "其他"];
  const CONDITIONS = ["全新", "九成新", "八成新", "七成新", "有明显使用痕迹"];
  const PRODUCTS = {
    DRAFT: "草稿", PENDING: "待审核", REJECTED: "已驳回", PUBLISHED: "已发布",
    RESERVED: "已预约", SOLD: "已售出", OFFLINE: "已下架", BANNED: "已封禁"
  };
  const BOOKINGS = {
    PENDING: "待卖家确认", ACCEPTED: "卖家已确认", COMPLETED: "已完成",
    CANCELLED: "已取消", REJECTED: "已拒绝", EXPIRED: "已过期"
  };
  const ACTIONS = {
    save: "保存草稿", submit: "提交审核", withdraw: "撤回审核", approve: "审核通过",
    rejectReview: "审核驳回", down: "下架商品", ban: "封禁商品", mark: "追加违规标记",
    book: "创建预约", accept: "接受预约", reject: "拒绝预约", cancel: "取消预约",
    complete: "确认收到实物", expire: "预约过期", delivery: "查看交付信息",
    grant: "授予管理权限", revoke: "撤销管理权限"
  };
  const SAMPLES = [
    { ID: "U-1001", name: "chen_buyer", role: "买家", admin: false },
    { ID: "U-1002", name: "lin_seller", role: "卖家", admin: false },
    { ID: "U-1003", name: "zhou_admin", role: "管理员", admin: true },
    { ID: "U-1004", name: "xu_student", role: "另一位买家", admin: false }
  ];

  class DemoError extends Error {
    constructor(code, message) {
      super(message);
      this.code = code;
    }
  }
  const fail = (code, message) => { throw new DemoError(code, message); };
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const active = (reservation) => ["PENDING", "ACCEPTED"].includes(reservation.status);
  const editable = (product) => ["DRAFT", "REJECTED", "OFFLINE"].includes(product.status);
  const bannable = (product) => ["PENDING", "REJECTED", "PUBLISHED", "RESERVED", "OFFLINE"].includes(product.status);
  const validImage = (src) => /^assets\/(?:keyboard|books|lamp|bag)\.jpg$/.test(src)
    || /^data:image\/(?:jpeg|png|webp);base64,[A-Za-z0-9+/]+=*$/.test(src);
  const shortDate = (time) => new Date(time + BEIJING).toISOString().slice(0, 10);
  const dateInput = (time) => new Date(time + BEIJING).toISOString().slice(0, 16);

  function readDate(value, endOfDay = false) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return NaN;
    const parsed = Date.parse(value + "T00:00:00+08:00");
    if (!Number.isFinite(parsed) || shortDate(parsed) !== value) return NaN;
    return parsed + (endOfDay ? DAY : 0);
  }

  function parseMoney(value) {
    const text = String(value).trim();
    if (!/^\d{1,6}(?:\.\d{1,2})?$/.test(text)) return NaN;
    const [whole, fraction = ""] = text.split(".");
    const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
    return cents <= 10000000 ? cents : NaN;
  }

  function find(items, ID) {
    return items.find((item) => item.ID === ID);
  }

  function makeSeed(now) {
    const accounts = SAMPLES.map(({ role, ...account }) => ({ ...account, demo: true }));
    const products = [];
    const reservations = [];
    const dayStart = readDate(shortDate(now));
    const p = (ID, sellerID, title, category, condition, cents, description, image, status, at) => {
      const content = { title, category, condition, cents, description, photos: image ? ["assets/" + image + ".jpg"] : [] };
      const hasPublished = ["PUBLISHED", "RESERVED", "SOLD", "OFFLINE"].includes(status);
      const product = {
        ID, sellerID, ...content, status, version: 1, createdAt: at - DAY, updatedAt: at,
        publishedAt: hasPublished ? at : null, approved: hasPublished ? JSON.stringify(content) : "",
        review: status === "PENDING" ? { ID: ID + "-S1", at, content } : null, reason: "", marks: []
      };
      products.push(product);
      return product;
    };
    p("P-1042", "U-1002", "75 键机械键盘", "电子产品", "九成新", 12000,
      "奶白色 75 键机械键盘，有线连接，按键功能正常。\n键帽有轻微使用痕迹，附数据线。", "keyboard", "PUBLISHED", now - 3600000);
    p("P-1043", "U-1002", "计算机基础教材套装", "书籍", "八成新", 2800,
      "两册教材合售，有少量划线笔记。", "books", "PUBLISHED", now - 7200000);
    p("P-1044", "U-1004", "暖白色折叠台灯", "生活用品", "九成新", 4200,
      "开合正常，灯光稳定，随附电源线。", "lamp", "PUBLISHED", now - 3 * 3600000);
    p("P-1081", "U-1002", "深绿尼龙双肩包", "生活用品", "八成新", 6500,
      "适合日常通勤。拉链完好，背带可调节。", "bag", "PUBLISHED", now - 4 * 3600000);
    p("P-1090", "U-1002", "计算机专业教材两册", "书籍", "八成新", 3800,
      "两册教材合售，有少量笔记。", "books", "PENDING", now - 1800000);
    p("P-1088", "U-1002", "折叠 LED 台灯", "生活用品", "九成新", 4500,
      "底座有轻微使用痕迹。", "lamp", "DRAFT", now - DAY);
    const occupied = p("P-1074", "U-1002", "深绿通勤双肩包", "生活用品", "八成新", 4800,
      "双肩包，拉链完整。", "bag", "RESERVED", now - DAY);
    const sold = p("P-1008", "U-1002", "桌面显示器支架", "生活用品", "九成新", 7000,
      "可调节支架，配件齐全。", "", "SOLD", now - 8 * DAY);
    const history = (ID, product, buyerID, status, createdAt, appointmentAt, confirmedAt, completedAt) => ({
      ID, productID: product.ID, buyerID, status, title: product.title, cents: product.cents,
      createdAt, appointmentAt, deadline: Math.min(createdAt + DAY, appointmentAt),
      place: "仙林校区图书馆正门外", confirmedAt, completedAt, closedAt: completedAt, reason: ""
    });
    const accepted = history("R-0433", occupied, "U-1004", "ACCEPTED", now - 7200000, now + DAY, now - 3600000, null);
    const completed = history("R-0419", sold, "U-1001", "COMPLETED", dayStart - 3 * DAY,
      dayStart - 2 * DAY, dayStart - 3 * DAY + 3600000, dayStart - 2 * DAY + 3600000);
    reservations.push(accepted, completed);
    return {
      schema: 1, accounts, products, reservations, results: [],
      logs: [
        { at: completed.completedAt, actorID: completed.buyerID, type: "complete", objectID: completed.ID,
          before: "卖家已确认 / 已预约", after: "已完成 / 已售出", outcome: "成功", reason: "", scope: [completed.buyerID, sold.sellerID] },
        { at: accepted.confirmedAt, actorID: occupied.sellerID, type: "accept", objectID: accepted.ID,
          before: "待卖家确认 / 已预约", after: "卖家已确认 / 已预约", outcome: "成功", reason: "", scope: [accepted.buyerID, occupied.sellerID] }
      ],
      next: { U: 1005, P: 1091, R: 434 }
    };
  }

  function createService(storage, clock = Date.now) {
    let local = makeSeed(clock());
    let persistent = Boolean(storage);
    if (persistent) {
      try {
        const key = DATABASE + "-check";
        storage.setItem(key, "1");
        storage.removeItem(key);
      } catch { persistent = false; }
    }

    function read() {
      if (persistent) {
        try {
          const raw = storage.getItem(DATABASE);
          if (raw) {
            const value = JSON.parse(raw);
            if (value.schema === 1 && Array.isArray(value.products) && Array.isArray(value.reservations)) local = value;
          }
        } catch { persistent = false; }
      }
      return copy(local);
    }

    function write(value) {
      if (persistent) {
        try {
          storage.setItem(DATABASE, JSON.stringify(value));
        } catch {
          fail("storage", "浏览器存储空间不足。本次没有保存，请删除部分商品照片后重试。");
        }
      }
      local = value;
    }

    function loginRequired(db, actorID) {
      const account = find(db.accounts, actorID);
      if (!account) fail("login", "请先登录后再操作。");
      return account;
    }

    function requireAdmin(account) {
      if (!account.admin) fail("access", "当前账号没有管理权限。");
    }

    function accountView(account) {
      return account && { ID: account.ID, name: account.name, admin: account.admin, demo: !!account.demo };
    }

    function nextID(db, kind) {
      const value = db.next[kind]++;
      return kind + "-" + String(value).padStart(4, "0");
    }

    function log(db, at, actorID, type, objectID, before, after, outcome, reason, scope) {
      db.logs.push({ at, actorID, type, objectID, before, after, outcome, reason, scope });
    }

    function pairedStatus(product, reservation) {
      return reservation ? BOOKINGS[reservation.status] + " / " + PRODUCTS[product.status]
        : product ? PRODUCTS[product.status] : "";
    }

    function releaseExpired(db, now) {
      let changed = 0;
      for (const reservation of db.reservations) {
        if (reservation.status !== "PENDING" || now < reservation.deadline) continue;
        const product = find(db.products, reservation.productID);
        if (!product || product.status !== "RESERVED") continue;
        const before = pairedStatus(product, reservation);
        reservation.status = "EXPIRED";
        reservation.closedAt = now;
        reservation.reason = "卖家未在确认截止前接受。";
        product.status = "PUBLISHED";
        product.version++;
        product.updatedAt = now;
        log(db, now, "system", "expire", reservation.ID, before, pairedStatus(product, reservation),
          "成功", reservation.reason, [product.sellerID, reservation.buyerID]);
        changed++;
      }
      return changed;
    }

    function expire() {
      const db = read();
      const changed = releaseExpired(db, clock());
      if (changed) write(db);
      return changed;
    }

    function checkVersion(product, cmd) {
      if (!product || Number(cmd.version) !== product.version) {
        fail("stale", "页面上的商品或预约状态已更新，请刷新后再操作。");
      }
    }

    function requireReason(reason) {
      if (!reason) fail("input", "请填写原因。");
      if ([...reason].length > 200) fail("input", "原因最多填写 200 字。");
    }

    function contentOf(fields, submitting) {
      const title = String(fields.title || "").trim();
      const category = String(fields.category || "");
      const condition = String(fields.condition || "");
      const description = String(fields.description || "").trim();
      const price = String(fields.price || "").trim();
      const cents = price ? parseMoney(price) : null;
      const photos = fields.photos || [];
      if ([...title].length > 60) fail("input", "商品标题最多 60 字。");
      if ([...description].length > 2000) fail("input", "商品描述最多 2000 字。");
      if (category && !CATEGORIES.includes(category)) fail("input", "请选择有效的商品分类。");
      if (condition && !CONDITIONS.includes(condition)) fail("input", "请选择有效的商品成色。");
      if (price && (!Number.isFinite(cents) || cents < 1)) fail("input", "价格需在 ¥0.01–¥100000.00 之间，最多两位小数。");
      if (!Array.isArray(photos) || photos.length > 5 || photos.some((src) => !validImage(src))) {
        fail("input", "最多上传 5 张有效的 JPEG 或 PNG 商品图片。");
      }
      if (submitting && (!title || !category || !condition || !description || cents === null)) {
        fail("input", "提交审核前请填写标题、分类、成色、价格和描述。");
      }
      return { title, category, condition, cents, description, photos };
    }

    const sellerCommands = ["save", "submit", "withdraw", "down"];
    const adminCommands = ["approve", "rejectReview", "ban", "mark", "grant", "revoke", "delivery"];
    const bookingCommands = ["accept", "reject", "cancel", "complete"];

    function context(db, actor, cmd) {
      if (adminCommands.includes(cmd.type)) requireAdmin(actor);
      const reservation = cmd.reservationID ? find(db.reservations, cmd.reservationID) : null;
      if (cmd.reservationID && !reservation) fail("access", "预约不存在或你没有查看权限。");
      const product = find(db.products, reservation?.productID || cmd.productID);
      if ((cmd.productID || reservation) && !product) fail("access", "商品不存在或你没有查看权限。");
      const owner = product?.sellerID === actor.ID;
      const buyer = reservation?.buyerID === actor.ID;
      if (sellerCommands.includes(cmd.type) && product && !owner) fail("access", "只能管理自己的商品。");
      if (bookingCommands.includes(cmd.type)) {
        if (!reservation || (!owner && !buyer)) fail("access", "预约不存在或你没有办理权限。");
        if (["accept", "reject"].includes(cmd.type) && !owner) fail("access", "只有商品卖家可处理待确认预约。");
        if (cmd.type === "complete" && !buyer) fail("access", "只有本单买家可确认收到实物。");
      }
      if (cmd.type === "book" && owner) fail("access", "不能预约自己发布的商品。");
      return {
        reservation, product, owner, buyer,
        objectID: reservation?.ID || product?.ID || cmd.accountID || "",
        scope: reservation && cmd.type !== "delivery" ? [product.sellerID, reservation.buyerID]
          : cmd.type === "down" && product?.status === "RESERVED" ? [product.sellerID] : []
      };
    }

    function apply(db, actor, cmd, ctx, now) {
      let { product, reservation } = ctx;
      const type = cmd.type;
      const reason = String(cmd.reason || "").trim();
      if (type === "grant" || type === "revoke") {
        const account = find(db.accounts, cmd.accountID);
        if (!account) fail("access", "找不到目标账号。");
        if (account.admin === (type === "grant")) fail("stale", "该账号权限已变化，请刷新。");
        if (type === "revoke" && db.accounts.filter((item) => item.admin).length <= 1) {
          fail("input", "至少需要保留一名有效管理员。");
        }
        const before = account.admin ? "管理员" : "普通账号";
        account.admin = type === "grant";
        return { objectID: account.ID, before, after: account.admin ? "管理员" : "普通账号", scope: [], reason };
      }
      if (type === "delivery") {
        if (!reservation) fail("access", "预约不存在或你没有查看权限。");
        return { objectID: reservation.ID, before: "", after: "", scope: [], reason: "管理端访问交付详情", outcome: "访问成功" };
      }

      const before = pairedStatus(product, reservation);
      if (type === "save" || type === "submit") {
        const content = contentOf(cmd.fields || {}, type === "submit");
        if (product) {
          checkVersion(product, cmd);
          if (!editable(product)) fail("stale", "商品当前不可编辑。待审核商品请先撤回，已发布商品请先下架。");
        } else {
          product = { ID: nextID(db, "P"), sellerID: actor.ID, status: "DRAFT", version: 0, createdAt: now,
            publishedAt: null, approved: "", review: null, reason: "", marks: [] };
          db.products.push(product);
        }
        Object.assign(product, content);
        if (type === "submit") {
          product.status = "PENDING";
          product.review = { ID: product.ID + "-S" + (product.version + 1), at: now, content: copy(content) };
          product.reason = "";
        }
      } else if (type === "book") {
        if (!product || product.status !== "PUBLISHED" || db.reservations.some((item) => item.productID === product.ID && active(item))) {
          fail(product?.status === "RESERVED" ? "occupied" : "unavailable",
            product?.status === "RESERVED" ? "商品已被预约，本次未创建预约。" : "商品当前不可预约，请返回集市。");
        }
        checkVersion(product, cmd);
        const place = String(cmd.place || "").trim();
        const input = String(cmd.appointment || "");
        const appointmentAt = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(input) ? Date.parse(input + ":00+08:00") : NaN;
        if (!Number.isFinite(appointmentAt) || dateInput(appointmentAt) !== input || appointmentAt <= now || appointmentAt > now + 30 * DAY) {
          fail("input", "交付时间需晚于现在，并在未来 30 天内（北京时间）。");
        }
        if ([...place].length < 2 || [...place].length > 100) fail("input", "请填写 2–100 字的校园公共交付地点。");
        reservation = {
          ID: nextID(db, "R"), productID: product.ID, buyerID: actor.ID, status: "PENDING",
          title: product.title, cents: product.cents, appointmentAt, place, createdAt: now,
          deadline: Math.min(now + DAY, appointmentAt), confirmedAt: null, completedAt: null, closedAt: null, reason: ""
        };
        db.reservations.push(reservation);
        product.status = "RESERVED";
      } else {
        if (!product) fail("access", "找不到要处理的商品。");
        if (bookingCommands.includes(type) && reservation?.status === "EXPIRED") {
          fail("expired", "预约已过期，请查看历史结果。");
        }
        checkVersion(product, cmd);
        switch (type) {
          case "withdraw":
            if (product.status !== "PENDING") fail("stale", "只有待审核商品可以撤回审核。");
            product.status = "DRAFT";
            product.review = null;
            break;
          case "approve":
          case "rejectReview":
            if (product.status !== "PENDING" || product.review?.ID !== cmd.reviewID) {
              fail("stale", "审核提交已经变化，请查看最新提交。");
            }
            if (type === "approve") {
              const reviewed = JSON.stringify(product.review.content);
              if (product.approved !== reviewed) product.publishedAt = now;
              product.approved = reviewed;
              product.status = "PUBLISHED";
              product.reason = "";
            } else {
              requireReason(reason);
              product.status = "REJECTED";
              product.reason = reason;
            }
            product.review = null;
            break;
          case "down":
            if (product.status !== "PUBLISHED") fail("stale", "请按当前状态处理商品。已有有效预约时需先处理预约。");
            product.status = "OFFLINE";
            break;
          case "ban":
            if (!bannable(product)) fail("stale", "商品当前不可封禁。已售出商品可以追加违规标记。");
            requireReason(reason);
            reservation = db.reservations.find((item) => item.productID === product.ID && active(item));
            if (reservation) {
              reservation.status = "CANCELLED";
              reservation.closedAt = now;
              reservation.reason = "平台封禁：" + reason;
            }
            product.status = "BANNED";
            product.review = null;
            product.reason = reason;
            break;
          case "mark":
            if (product.status !== "SOLD") fail("stale", "该操作仅适用于已售出商品。");
            requireReason(reason);
            product.marks.push({ at: now, reason, actorID: actor.ID });
            break;
          case "accept":
          case "reject":
          case "cancel":
          case "complete": {
            if (!active(reservation) || product.status !== "RESERVED") fail("stale", "预约已结束，请刷新查看结果。");
            if (type === "accept" || type === "reject") {
              if (reservation.status !== "PENDING") fail("stale", "该预约已不处于待卖家确认状态。");
              if (type === "accept") {
                reservation.status = "ACCEPTED";
                reservation.confirmedAt = now;
              } else {
                requireReason(reason);
                reservation.status = "REJECTED";
                product.status = "PUBLISHED";
              }
            } else if (type === "cancel") {
              if (reservation.status === "PENDING" && !ctx.buyer) fail("access", "待确认阶段，卖家可拒绝预约。");
              if (reservation.status === "ACCEPTED") requireReason(reason);
              reservation.status = "CANCELLED";
              product.status = "PUBLISHED";
            } else {
              if (reservation.status !== "ACCEPTED") fail("stale", "卖家确认预约后，买家才可确认收到实物。");
              if (cmd.received !== true) fail("input", "请先勾选我已收到实物。");
              reservation.status = "COMPLETED";
              reservation.completedAt = now;
              product.status = "SOLD";
            }
            if (!active(reservation)) {
              reservation.closedAt = now;
              reservation.reason = reason;
            }
            break;
          }
          default:
            fail("input", "不支持该操作。");
        }
      }
      product.version++;
      product.updatedAt = now;
      return {
        productID: product.ID, reservationID: reservation?.ID, before, after: pairedStatus(product, reservation),
        objectID: type === "ban" ? product.ID : reservation?.ID || product.ID,
        scope: reservation ? [product.sellerID, reservation.buyerID] : [], reason
      };
    }

    function fingerprint(cmd) {
      return JSON.stringify(Object.keys(cmd).filter((key) => key !== "token").sort().map((key) => [key, cmd[key]]));
    }

    function command(actorID, cmd) {
      let db = read();
      const actor = loginRequired(db, actorID);
      let ctx = context(db, actor, cmd);
      const cached = cmd.token && db.results.find((entry) => entry.actorID === actorID && entry.type === cmd.type && entry.token === cmd.token);
      const signature = cmd.token ? fingerprint(cmd) : "";
      if (cached) {
        if (cached.signature !== signature) fail("conflict", "提交内容已经变化，请刷新并重新操作。");
        if (cached.error) fail(cached.error.code, cached.error.message);
        return copy(cached.result);
      }
      const now = clock();
      if (["book", "accept"].includes(cmd.type) && releaseExpired(db, now)) {
        write(db);
        db = read();
        ctx = context(db, actor, cmd);
      }
      const draft = copy(db);
      let result;
      try {
        result = apply(draft, actor, cmd, context(draft, actor, cmd), now);
      } catch (error) {
        if (!(error instanceof DemoError)) throw error;
        log(db, now, actorID, cmd.type, ctx.objectID, pairedStatus(ctx.product, ctx.reservation),
          pairedStatus(ctx.product, ctx.reservation), "失败", error.message, ctx.scope);
        if (cmd.token) db.results.push({ actorID, type: cmd.type, token: cmd.token, signature,
          error: { code: error.code, message: error.message } });
        write(db);
        throw error;
      }
      log(draft, now, actorID, cmd.type, result.objectID, result.before, result.after, result.outcome || "成功", result.reason, result.scope);
      if (cmd.token) draft.results.push({ actorID, type: cmd.type, token: cmd.token, signature, result });
      write(draft);
      return result;
    }

    async function hash(password, salt) {
      if (!globalThis.crypto?.subtle) fail("input", "请用 Chrome 或 Edge 打开此演示以注册新账号。");
      const data = new TextEncoder().encode(salt + ":" + password);
      const bytes = new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", data));
      return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
    }

    async function login(name, password) {
      const db = read();
      const account = db.accounts.find((item) => item.name.toLowerCase() === String(name).trim().toLowerCase());
      const verified = account && (account.demo ? password === DEMO_PASSWORD : await hash(password, account.salt) === account.hash);
      if (!verified) fail("input", "用户名或密码不正确。");
      return accountView(account);
    }

    async function register(name, password) {
      name = String(name).trim();
      if (!/^[A-Za-z0-9_]{4,20}$/.test(name)) fail("input", "用户名需为 4–20 位字母、数字或下划线。");
      if ([...password].length < 10 || [...password].length > 64) fail("input", "密码长度需在 10–64 位之间。");
      const salt = globalThis.crypto.randomUUID();
      const verifier = await hash(password, salt);
      const db = read();
      if (db.accounts.some((item) => item.name.toLowerCase() === name.toLowerCase())) fail("input", "用户名已被使用。");
      const account = { ID: nextID(db, "U"), name, salt, hash: verifier, admin: false };
      db.accounts.push(account);
      write(db);
      return accountView(account);
    }

    function snapshot(actorID) {
      const db = read();
      const actor = find(db.accounts, actorID);
      const admin = !!actor?.admin;
      const products = db.products.filter((item) => item.status === "PUBLISHED" || item.sellerID === actorID || admin);
      const reservations = actor ? db.reservations.filter((item) => {
        const sellerID = find(db.products, item.productID)?.sellerID;
        return admin || item.buyerID === actorID || sellerID === actorID;
      }).map((item) => {
        const sellerID = find(db.products, item.productID)?.sellerID;
        const participant = item.buyerID === actorID || sellerID === actorID;
        return { ...item, sellerID, place: participant ? item.place : undefined, appointmentAt: participant ? item.appointmentAt : undefined };
      }) : [];
      return {
        actor: accountView(actor), accounts: db.accounts.map(({ ID, name, admin: canManage }) => ({ ID, name, admin: canManage })),
        products, reservations, logs: actor ? db.logs.filter((item) => admin || item.scope.includes(actorID)) : []
      };
    }

    function bookingDetail(actorID, reservationID, access = false) {
      const db = read();
      const actor = loginRequired(db, actorID);
      const reservation = find(db.reservations, reservationID);
      const product = find(db.products, reservation?.productID);
      if (!product) fail("access", "预约不存在或你没有查看权限。");
      const participant = actorID === product.sellerID || actorID === reservation.buyerID;
      if (!participant && !actor.admin) fail("access", "预约不存在或你没有查看权限。");
      if (!participant && access) command(actorID, { type: "delivery", reservationID });
      return {
        ...reservation, product, sellerID: product.sellerID,
        place: participant || access ? reservation.place : "",
        appointmentAt: participant || access ? reservation.appointmentAt : null,
        privateVisible: participant || access
      };
    }

    return {
      snapshot, expire, command, login, register, bookingDetail,
      reset() { write(makeSeed(clock())); },
      get persistent() { return persistent; }
    };
  }

  globalThis.MarketDemo = {
    createService, DemoError, PRODUCTS, BOOKINGS, ACTIONS, CATEGORIES, CONDITIONS, SAMPLES,
    DEMO_PASSWORD, DAY, editable, bannable, active, parseMoney, validImage, dateInput, shortDate, readDate
  };
}());
