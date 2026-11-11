"""Render the lab report from the current UML and UI exports."""

from pathlib import Path
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "实验报告.pdf"
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 46
WIDTH = PAGE_WIDTH - 2 * MARGIN
BOTTOM = 49
INK = colors.HexColor("#22263A")
MUTED = colors.HexColor("#50576D")
ACCENT = colors.HexColor("#49358A")
LINE = colors.HexColor("#DBDDE7")
TINT = colors.HexColor("#F2F0F9")


def register_fonts():
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    pdfmetrics.registerFont(TTFont("YaHei", str(fonts / "msyh.ttc"), subfontIndex=0))
    pdfmetrics.registerFont(TTFont("YaHeiBold", str(fonts / "msyhbd.ttc"), subfontIndex=0))
    pdfmetrics.registerFontFamily("YaHei", normal="YaHei", bold="YaHeiBold")


def style(name, size, leading, color=INK, font="YaHei"):
    return ParagraphStyle(
        name, fontName=font, fontSize=size, leading=leading, textColor=color,
        wordWrap="CJK", allowWidows=0, allowOrphans=0,
    )


class Report:
    def __init__(self, output):
        self.pdf = Canvas(str(output), pagesize=A4, pageCompression=1)
        self.pdf.setTitle("软件工程实验二 · 软件设计与建模")
        self.pdf.setAuthor("李宇轩")
        self.pdf.setCreator("ReportLab")
        self.pdf.setSubject("校园二手交易系统设计")
        self.body = style("body", 10.7, 17.7)
        self.small = style("small", 9.4, 15.0, MUTED)
        self.subhead = style("subhead", 13.4, 20.5, ACCENT, "YaHeiBold")
        self.title_style = style("title", 23, 30, INK, "YaHeiBold")
        self.cell = style("cell", 9.65, 15.4)
        self.cell_header = style("cell_header", 9.55, 15.4, ACCENT, "YaHeiBold")
        self.page_number = 0
        self.figure_number = 0
        self.page_title = ""
        self.y = 0

    def line(self, y):
        self.pdf.setStrokeColor(LINE)
        self.pdf.setLineWidth(0.6)
        self.pdf.line(MARGIN, y, PAGE_WIDTH - MARGIN, y)

    def label(self, text, x, y, size=9, color=MUTED, bold=False):
        self.pdf.setFont("YaHeiBold" if bold else "YaHei", size)
        self.pdf.setFillColor(color)
        self.pdf.drawString(x, y, text)

    def add(self, item, gap=0):
        _, height = item.wrapOn(self.pdf, WIDTH, self.y - BOTTOM)
        bottom = self.y - height
        if bottom < BOTTOM:
            raise ValueError(f"Page {self.page_number} ({self.page_title}) overflows at {bottom:.1f} pt")
        item.drawOn(self.pdf, MARGIN, bottom)
        self.y = bottom - gap

    def paragraph(self, text, *, small=False, gap=8):
        self.add(Paragraph(text, self.small if small else self.body), gap)

    def subheading(self, title):
        self.add(Paragraph(title, self.subhead), 5)

    def table(self, rows, first_width):
        cells = [
            [Paragraph(text, self.cell_header if index == 0 else self.cell) for text in row]
            for index, row in enumerate(rows)
        ]
        table = Table(cells, colWidths=[first_width, WIDTH - first_width])
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, 0), TINT),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        self.add(table, 12)

    def figure(self, directory, file, caption, *, max_width=WIDTH, max_height=570, gap=9):
        reader = ImageReader(str(ROOT / directory / f"{file}.png"))
        native_width, native_height = reader.getSize()
        scale = min(max_width / native_width, max_height / native_height)
        width, height = native_width * scale, native_height * scale
        bottom = self.y - height
        if bottom < BOTTOM:
            raise ValueError(f"Figure {file} overflows on page {self.page_number}")
        x = (PAGE_WIDTH - width) / 2
        self.pdf.drawImage(reader, x, bottom, width=width, height=height, mask="auto")
        self.pdf.setStrokeColor(LINE)
        self.pdf.setLineWidth(0.4)
        self.pdf.rect(x, bottom, width, height, stroke=1, fill=0)
        self.y = bottom - 5
        self.figure_number += 1
        self.paragraph(f"<b>图 {self.figure_number}</b>　{caption}", small=True, gap=gap)

    def page(self, title, section, destination=None):
        self.page_number += 1
        self.page_title = title
        self.y = PAGE_HEIGHT - 78
        self.label("南大集市  /  软件工程实验二", MARGIN, PAGE_HEIGHT - 32, bold=True)
        self.line(PAGE_HEIGHT - 42)
        self.label(section, MARGIN, PAGE_HEIGHT - 66, size=9.5, color=ACCENT, bold=True)
        if destination:
            self.pdf.bookmarkPage(destination)
            self.pdf.addOutlineEntry(title, destination)
        self.add(Paragraph(title, self.title_style), 9)

    def end_page(self):
        self.line(40)
        self.label("校园二手交易系统", MARGIN, 23, size=8)
        self.pdf.setFont("YaHei", 8)
        self.pdf.drawRightString(PAGE_WIDTH - MARGIN, 23, str(self.page_number))
        self.pdf.showPage()

    def cover(self):
        self.page_number = 1
        self.page_title = "封面"
        self.pdf.bookmarkPage("cover")
        self.pdf.addOutlineEntry("封面", "cover")
        self.pdf.setFillColor(ACCENT)
        self.pdf.rect(MARGIN, PAGE_HEIGHT - 63, WIDTH, 3, stroke=0, fill=1)
        self.label("软件工程 · 实验二", MARGIN, PAGE_HEIGHT - 94, 12, ACCENT, True)
        self.label("软件设计与建模", MARGIN, PAGE_HEIGHT - 155, 38, INK, True)
        self.label("南大集市", MARGIN, PAGE_HEIGHT - 210, 31, ACCENT, True)
        self.label("校园二手交易系统设计报告", MARGIN, PAGE_HEIGHT - 244, 14)
        self.y = PAGE_HEIGHT - 288
        self.table([
            ("学号与姓名", "241220176　李宇轩"),
            ("实验课程", "软件工程"),
            ("成稿日期", "2026 年 11 月 12 日"),
        ], 104)
        self.y -= 26
        self.subheading("目录")
        for title, destination, page_range in [
            ("项目范围与主要功能", "scope", "2"),
            ("系统架构与 UML 设计", "architecture", "3-10"),
            ("功能模块与 UI 原型", "ui", "11-17"),
            ("AI 辅助、人工审查与验证", "ai", "18-21"),
        ]:
            y = self.y - 14
            self.label(title, MARGIN, y, 11)
            self.pdf.setFont("YaHei", 10)
            self.pdf.drawRightString(PAGE_WIDTH - MARGIN, y, page_range)
            self.pdf.linkRect("", destination, (MARGIN, y - 7, PAGE_WIDTH - MARGIN, y + 15), thickness=0)
            self.line(y - 9)
            self.y -= 34
        self.end_page()

    def log_entry(self, number, scene, output_and_limit, revision):
        self.paragraph(f"<b>{number:02d}　{scene}</b>　{output_and_limit}<br/><b>调整</b>　{revision}", gap=13)


def add_scope(report):
    report.page("项目范围与主要功能", "一　项目与需求", "scope")
    report.paragraph(
        "南大集市服务于校园内单件二手物品交易。访客浏览可预约商品，普通账号可作为买家或卖家。卖家发布的商品经管理员审核后公开，"
        "买家填写交付约定并独占预约，卖家接受后双方线下交付，由买家确认完成。款项由双方线下处理。"
    )
    report.paragraph(
        "本设计沿用实验一 lab1-final（提交 81b7509）的 32 条需求。下表列出六个功能模块的职责和主要需求。"
        "REQ-023、028 分别贯穿数据关联及保存、核心界面可操作性。"
    )
    report.table([
        ("功能模块", "职责与对应需求"),
        ("账号与权限", "普通账号注册、登录、访客访问、管理员授撤权和对象访问。密码哈希及服务端鉴权对应 REQ-001 至 004、029 至 030。"),
        ("商品管理与浏览", "草稿、编辑、送审与撤回、卖家下架。公开页按关键词、分类和价格组合查询，每页 20 件。对应 REQ-005 至 007、009、011、031。"),
        ("审核与违规处置", "核对当前提交的快照，审核通过或说明驳回原因。封禁联动结束待审提交或有效预约，已售出商品可追加违规标记。对应 REQ-008、010。"),
        ("预约与交付", "独占预约、原交付约定、卖家接受或拒绝、双方取消、待确认过期、买家完成与历史查询，处理重复提交和旧页面。对应 REQ-012 至 022、032。"),
        ("操作记录", "记录关键变更和获授权的敏感访问，按主体和对象权限检索。成功记录随业务共同提交。对应 REQ-024 至 026。"),
        ("交易统计", "卖家查看本人商品和成交，管理员查看平台。分别统计当前状态与指定时段内首次完成的交易。对应 REQ-027。"),
    ], 108)
    report.subheading("交易主线")
    report.paragraph(
        "卖家编辑并送审 → 管理员通过 → 买家筛选并预约 → 卖家接受 → 买家确认线下交付 → 平台保留原价、约定和首次完成时间。"
        "未确认的预约可被取消、拒绝或到期释放。已售出和已封禁为商品的终态。"
    )
    report.subheading("建模与界面制品")
    report.paragraph(
        "PlantUML 图覆盖结构类图和组件图、行为状态图、交互时序图。报告收录 8 张完整图。draw.io 的 21 个画板覆盖正常操作和异常反馈，"
        "报告展示代表界面，提交包提供各画板的完整 PNG。"
    )
    report.end_page()


def add_architecture(report):
    report.page("系统组件与模块依赖", "二　软件架构与 UML", "architecture")
    report.paragraph(
        "采用模块化单体与一个 PostgreSQL 数据库。Web 请求进入各功能 API，受保护的请求先通过账号组件鉴权。商品、审核、预约的写操作交由"
        " ProductWorkflow，查询服务读取列表、详情和统计。到期任务调用同一工作流。"
    )
    report.figure("UML", "UML组件图", "组件图。路由、应用服务、领域与持久化的调用方向。", max_height=463)
    report.paragraph(
        "<b>事务所有者</b>　ProductWorkflow 建立事务并通过同一连接保存商品、预约或审核提交、最终操作结果及成功审计。"
        "读取详情使用联表查询或一致快照。获授权的管理员读取私有交付约定时，查询服务追加访问记录。"
    )
    report.paragraph(
        "<b>设计原因</b>　一条业务命令可同时影响商品和预约，集中写入口可以统一锁顺序、权限复查和版本检查。"
        "查询、认证和统计维持各自职责，交易状态由同一领域入口改变。"
    )
    report.end_page()

    report.page("核心领域类图", "二　软件架构与 UML", "domain")
    report.paragraph(
        "Product 是商品、预约和审核状态联动的入口。账号可在不同交易中充当买家或卖家。商品的卖家及预约所属的商品固定，"
        "预约的卖家由所属商品推导，创建时禁止自购。"
    )
    report.figure("UML", "UML类图", "类图。对象关联、业务接口、值对象和关键快照。", max_height=509)
    report.paragraph(
        "<b>派生与快照</b>　当前预约、当前送审与确认截止由已有记录计算。预约保存原价和交付条款。"
        "送审记录保存当次内容与图片引用，供后续追溯。"
    )
    report.paragraph(
        "<b>唯一并发版本</b>　商品持有整个交易关系的 version。接受预约虽然保持商品为已预约，也须递增 version。"
        "类图以关联表达归属，数据库通过外键存储该关系。"
    )
    report.end_page()

    report.page("应用与记录类图", "二　软件架构与 UML", "application")
    report.paragraph(
        "ProductWorkflow 编排命令与到期处理。OperationResult 以用户、动作和提交标记组成的 K 定位一次请求，"
        "保存目标、内容摘要、最终结果和结果对象引用。"
    )
    report.figure("UML", "UML类图_应用与记录", "类图。统一写入口、最终结果、审计记录和查询职责。", max_height=440)
    report.paragraph(
        "<b>最终结果</b>　结果表只保存 SUCCESS 或 REJECTED。已提交的创建结果可以在预约后续取消后恢复，"
        "响应同时携带原预约 ID、原提交结果和当前状态。重复请求按当前权限读取。"
    )
    report.paragraph(
        "<b>审计职责</b>　AuditEntry 是 REQ-024 至 026 的支撑记录，分别记录成功变更、失败和敏感读取。"
        "成功变更随业务共同提交。技术失败先回滚，随后尽力追加失败记录。交易守卫与幂等恢复分别由领域方法及结果表承担。"
    )
    report.paragraph(
        "<b>持久化与留存</b>　账号、商品、送审、预约、操作结果与审计记录写入数据库，商品图片通过文件引用关联。"
        "业务记录、操作结果和审计至少保留 180 天，本期保留历史，起算规则沿用实验一待确认事项。"
    )
    report.end_page()

    report.page("商品状态与业务接口", "二　软件架构与 UML", "product-state")
    report.paragraph(
        "商品有草稿、待审核、已驳回、已发布、已下架、已预约、已售出和已封禁八个状态。编辑及送审面向草稿、已驳回和已下架。"
        "审核只作用于当前提交，首次通过或改动后通过时更新发布时间。"
    )
    report.figure("UML", "UML状态图_商品", "状态图。商品转换守卫、角色和对应的 Product 方法。", max_height=492)
    report.paragraph(
        "<b>撤回与下架</b>　withdrawReview 关闭当前待审提交并回到草稿。takeDown 要求商品已发布且无有效预约。"
        "已预约商品的卖家先按预约规则办理，之后可按最新商品状态尝试下架。"
    )
    report.paragraph(
        "<b>处置</b>　ban 将合法的可封禁商品置为已封禁，同时结束当前待审提交或取消有效预约。"
        "已售出商品通过 markViolation 追加标记，保留原成交状态和历史。"
    )
    report.end_page()

    report.page("预约状态与共同不变量", "二　软件架构与 UML", "reservation-state")
    report.paragraph(
        "预约从待卖家确认开始。卖家须在截止前接受，也可说明原因拒绝。待确认时买家可取消，确认后双方均可说明原因取消。"
        "只有当前已确认预约的买家能确认交付完成。"
    )
    report.figure("UML", "UML状态图_预约", "状态图。预约的六个状态及其对商品的同步影响。", max_height=275)
    report.table([
        ("共同约束", "成功提交后的要求"),
        ("I1 / I2　占用", "有效预约指待确认或已确认。每件商品至多一条有效预约，商品已预约当且仅当有一条有效预约。"),
        ("I3　成交", "商品已售出当且仅当恰有一条已完成预约，此时有效预约数为零。"),
        ("I4 / I5　历史", "预约卖家等于商品卖家，买家为其他账号。终态保留原价与交付约定，首次完成时间只写一次。"),
        ("I6 / I7　提交", "成功变更、最终结果和成功审计共同提交。新命令核对商品版本，每次实际变更递增一次。"),
    ], 112)
    report.paragraph(
        "条件唯一索引约束有效预约和完成预约的数量。跨表状态等价由统一入口在商品锁内调用领域方法并共同保存。"
        "到期处理只结束锁内重读后仍是当前且待确认的指定预约。"
    )
    report.end_page()

    report.page("正常预约", "二　软件架构与 UML", "sequence-create")
    report.paragraph(
        "买家提交交付约定、商品版本和本次提交标记。应用服务先取得事务级 K 锁，随后锁住商品行。"
        "按锁后新读的当前状态核对角色、版本、预约归属和参数。"
    )
    report.figure("UML", "UML时序图_正常预约", "时序图。创建预约、更新商品和写入最终结果的共同事务。", max_height=476)
    report.paragraph(
        "<b>成功与失败</b>　领域入口建立待确认预约并将商品置为已预约。数据库共同写入新版本、预约、SUCCESS 及成功审计，"
        "提交确认后才返回。任一必要写入失败都回滚。确定的业务拒绝在业务改动前判定，保存 REJECTED 和失败原因。"
    )
    report.paragraph(
        "<b>到期先行</b>　截止为创建后 24 小时与约定交付时间的较早值。创建或接受入口发现已有待确认预约到期时，先退出未写业务的事务，"
        "再独立提交过期释放并重入原命令。后续仍检查原页面版本，已完成的释放继续有效。"
    )
    report.end_page()

    report.page("并发竞争与卖家下架", "二　软件架构与 UML", "sequence-race")
    report.paragraph(
        "两名买家与卖家提交同一已发布版本，三个 K 各异，写操作竞争同一商品行锁。<br/>"
        "事务采用 READ COMMITTED。后续请求获锁后重读已提交的关联和版本，再核对操作条件。"
    )
    report.figure("UML", "UML时序图_并发竞争", "时序图。两笔预约和一次下架争用同一商品。", max_height=505)
    report.paragraph(
        "<b>预约先提交</b>　首位买家得到唯一有效预约，另一个买家和卖家的旧版本请求被拒绝。<br/>"
        "<b>下架先提交</b>　商品已下架，两位买家均无法建立预约。"
    )
    report.paragraph(
        "<b>先持锁的事务回滚</b>　下一请求继续按最后已提交状态判断。三个动作的六种顺序均可归入以上提交结果。"
        "待审商品的撤回审核只关闭待审提交，此时商品本身不可预约。"
    )
    report.end_page()

    report.page("幂等重试与结果恢复", "二　软件架构与 UML", "sequence-retry")
    report.paragraph(
        "同一提交使用原 K 和原请求内容。K 锁是事务级的，等待者取得锁后重新读取最终结果。提交和回滚都会释放锁，"
        "持久化状态只记录已确定结果。"
    )
    report.figure("UML", "UML时序图_幂等重试", "时序图。等待、失败回滚、响应丢失与原结果返回。", max_height=505)
    report.paragraph(
        "<b>查无结果</b>　原事务已回滚时，按锁内新读的条件重新执行。等待超时只结束本次等待，客户端继续使用原 K。"
        "<b>查到结果</b>　校验目标、摘要与当前访问权限后返回原结果和当前状态。"
    )
    report.paragraph(
        "提交阶段断线时，客户端保留原标记和请求，先查询本次结果。同一标记对应不同请求内容时报告冲突并保留原记录。"
        "这使预约创建成功和其可恢复结果共享同一个提交事实。"
    )
    report.end_page()


def add_ui(report):
    pages = [
        (
            "账号与权限", "ui",
            "登录区供普通账号进入业务，04 提供普通账号注册。16 由管理员查询账号与授撤权，撤权确认须保留至少一名有效管理员。",
            ("03_账号登录", "账号登录。继续原操作或返回集市，注册可从登录页进入。"),
            ("16_权限管理", "权限管理。展示账号当前权限和可执行操作。"),
        ),
        (
            "商品管理与浏览", "ui-products",
            "访客可按关键词、分类和价格组合筛选。02 展示商品详情，06 用于编辑草稿或送审。卖家在 05 按状态办理商品。",
            ("01_集市浏览", "公开集市。按发布时间排序并分页显示可预约商品。"),
            ("05_我的商品", "我的商品。待审可撤回，已发布且无有效预约可下架，已预约可查看当前预约。"),
        ),
        (
            "审核与违规处置", "ui-review",
            "管理员对当前送审快照作审核决定。封禁前确认联动范围，影响有效预约时同步保存平台取消原因，便于买卖双方查询。",
            ("14_商品审核", "商品审核。核对提交 ID、送审内容与审核决定。"),
            ("15_违规处置", "违规处置。显示封禁影响，已售出商品可追加违规标记。"),
        ),
        (
            "预约与交付", "ui-reservation",
            "买家填写未来 30 天内的交付时间与地点。08 查看进度，09 由卖家处理。买家经 10 确认收货，成交记录见 11。",
            ("07_提交预约", "提交预约。固定交付约定和预约时价格。"),
            ("09_卖家处理预约", "卖家处理。展示当前预约、接受截止及接受或拒绝操作。"),
        ),
        (
            "预约反馈与恢复", "ui-recovery",
            "结果未知时保留本次请求供查询。已明确发生竞争时，刷新页面取得最新状态。21 保留已过期预约的历史约定并引导返回集市。",
            ("12_预约结果待确认", "结果待确认。使用原提交标记查询本次结果。"),
            ("13_商品状态已变", "状态冲突。商品已被其他买家预约，给出可执行的刷新入口。"),
        ),
        (
            "操作记录", "ui-audit",
            "日志可按对象 ID、动作、操作人、结果与时间筛选。管理员查阅平台记录，普通账号只检索有权访问的个人操作和交易记录。",
            ("17_平台操作记录", "平台操作记录。区分成功变更、失败与敏感访问。"),
            ("18_我的操作记录", "我的操作记录。面向本人及有权查看的相关业务对象。"),
        ),
        (
            "交易统计", "ui-stats",
            "成交按北京时间左闭右开区间内的首次完成时间计数，约定总额按预约时价格求和。当前商品状态数量独立统计。",
            ("19_卖家交易统计", "卖家交易统计。查询范围为自己的商品与成交。"),
            ("20_平台交易统计", "平台交易统计。管理员查看平台范围的状态和交易汇总。"),
        ),
    ]
    for title, destination, lead, first, second in pages:
        report.page(title, "三　功能模块与 UI 原型", destination)
        report.paragraph(lead, gap=5)
        for filename, caption in (first, second):
            number = filename.split("_", 1)[0]
            report.figure("UI界面", filename, f"画板 {number} · {caption}", max_width=433, gap=7)
        report.end_page()


def add_ai_log(report):
    report.page("AI 辅助记录 · 需求与建模", "四　AI 使用与人工审查", "ai")
    report.paragraph("以下按本实验中的可追溯交互记录，逐项列出使用场景、生成结果、适用性与限制，以及形成的修订。", gap=14)
    for entry in [
        (1, "识别课程要求", "AI 根据课程页入口和用户提供的正文提取作业任务。摘要便于梳理，容易弱化四种 UML 类型与人工修改记录的细则。",
         "以粘贴的完整要求逐项核对 UML 类别、报告栏目、工具和 ZIP 结构。"),
        (2, "参考旧资料", "用户提供 2.md 与另一位同学的 ZIP。AI 用参考件理解组织形式，旧版学号、日期和项目内容只适用于参考件。",
         "实验二采用本次课程要求和本人的实验一需求。"),
        (3, "拟定架构", "AI 根据实验一整理六个模块和预约主线。按模块快速分解有帮助，初稿对重复提交和跨状态写入约束仍粗略。",
         "确定单体架构，将商品、审核和预约写操作归入同一交易入口，结合后续审查明确事务。"),
        (4, "整理实验流程", "AI 对照已有需求给出 UML、UI、审查、Git 和组包顺序。清单便于分步执行，完成状态须由实际制品核对。",
         "先出 UML 与解析，再检查缺项并进入界面阶段。"),
        (5, "生成 UML 与逐图解释", "AI 编写 PlantUML 和配套解析。源文件便于重绘和比较，最初渲染的阅读顺序和连线可读性不足。",
         "逐图核对主题与类型，保留图和源文件，按用户的版式反馈重排。"),
        (6, "首次进度核对", "AI 将已产出的建模材料与课程交付项对照，指出界面、报告和组包待办。清单的进度依赖当时版本。",
         "以实际文件和用户审查为阶段检查点，后续再次核对。"),
        (7, "改善图形排版", "AI 重排图面。分组及对齐可以帮助顺着主线读图。用户明确问题是排版，语言调整无法解决结构拥挤。",
         "保留既有语言选择，优先调整分组、对齐、连线路径及主题拆分。"),
    ]:
        report.log_entry(*entry)
    report.end_page()

    report.page("AI 辅助记录 · 设计审查", "四　AI 使用与人工审查", "ai-review")
    for entry in [
        (8, "规范 ID 拼写", "AI 检查图内标识符。统一词形方便跨图搜索，代码与业务文档的命名语境有差异。",
         "依用户要求在设计标识符中统一用 ID 或 id，PlantUML 制品检查覆盖该规则。"),
        (9, "解释类图", "AI 说明对象关系、角色、状态与快照。解释便于核对职责，也暴露了重复字段及卖家关系未受约束的问题。",
         "采用派生预约卖家和当前占用，将技术记录另列为应用与记录类图。"),
        (10, "解释并发原理", "AI 用商品版本、锁和幂等识别解释多个请求的执行顺序。仅列机制难以判断丢响应和中间失败。",
         "加入可观察的提交结果与回滚分支，并列出两位买家和卖家下架的竞争。"),
        (11, "落实十项人工意见", "用户指出原子结果、跨状态约束、职责、依赖、审计、接口、卖家一致性和竞争路径等问题，并要求三张时序图与克制的架构。AI 生成修订图与模型，可逐项核对设计并枚举边界案例。",
         "保留真实旧稿，补齐 I1 至 I7 与共同事务，审计归为支撑，三张时序图分别验证正常、竞争和重试。模型覆盖仍以真实数据库语义为前提。"),
        (12, "再次核对进度", "AI 按制品核对四种 UML、模型和报告缺项。文件存在与个人评审是不同的证据。",
         "用户明确下一步先完成 UI，随后提交首轮 Git。"),
        (13, "生成界面设计", "AI 用 draw.io 制作六模块 21 个画板并导出 PNG。复用图元能保持风格一致，状态反馈和数据口径仍需逐页校对。",
         "分开展示结果未知、竞争冲突和过期，区分公开、卖家及管理员的权限和状态。"),
        (14, "生成样例图片", "imagegen 生成四格商品样例照片。照片风格一致，型号、价格与真实来源无法从生成图确认。",
         "裁成独立素材，商品文字和价格由 draw.io 图元及演示数据表达。"),
    ]:
        report.log_entry(*entry)
    report.end_page()

    report.page("AI 辅助记录 · 原型与成稿", "四　AI 使用与人工审查", "ai-prototype")
    for entry in [
        (15, "Git 版本记录", "AI 保存本地阶段制品，之后在项目仓库分版归档。Git 可以对照源文件和图片，初版须以实际留下的文件为准。",
         "从存档恢复审查前 UML，以 lab2-ai-draft 保存。"),
        (16, "说明界面入口", "AI 提供 draw.io 画板和导出图的访问方式。该入口支持查看设计和链接跳转，实际浏览器操作还需网页。",
         "保留可编辑画板及 PNG，后续补充可直接打开的前端入口。"),
        (17, "梳理后续实验步骤", "AI 根据当前材料列出验收、修订、成稿与组包。流程能指出依赖，具体进度以用户反馈为准。",
         "先让用户核对业务和界面，再把结果写入最终材料。"),
        (18, "列出人工审核项", "AI 汇总状态联动、三种时序、模块权限与界面等核对项。清单帮助定位文档和场景，人工结论取自实际反馈。",
         "以用户指出的浏览器无法打开问题作为下一轮修订的起点。"),
        (19, "制作可运行网页", "AI 写出 HTML、CSS、JavaScript 本地网页并点验角色和流程。浏览器可操作实际页面状态，演示数据保存在浏览器。",
         "增加本地打开说明和 HTTP 备用入口。用户确认可进入下一步，验收记录纳入人工审核修改版。"),
        (20, "辅助撰写和组包", "AI 将设计、画板和实际审查整理成报告。自动检查能比对 PDF 内容和 ZIP 文件，图文布局及技术表述仍需对照渲染和原始材料。",
         "逐页核对图文，把核心类图里缺字的两个等价符号改为文字。按课程清单封装并比对文件。"),
    ]:
        report.log_entry(*entry)
    report.subheading("人工参与")
    report.paragraph(
        "用户明确了排版和 ID 规范，审查并提出十项 UML 问题，指出浏览器入口缺陷，随后检查网页原型并确认可继续。"
        "修订文件和提交由 AI 执行，报告据实记录审查决策和验收。"
    )
    report.end_page()

    report.page("工作流、验证与版本记录", "四　AI 使用与人工审查", "validation")
    report.subheading("人只做检查校对的条件")
    report.paragraph(
        "本次初稿可以很快形成，但人工审查改变了多项业务设计。例如，两位买家与卖家下架的竞争要以首个成功提交判定，"
        "丢响应后的重试必须找回原预约。只校对图和措辞会漏掉这些未写清的规则。"
    )
    report.paragraph(
        "可将已明确的业务规则和失败案例整理成输入，交由 AI 生成 PlantUML、画板草案和报告，并自动检查语法、标识符、模型及交付结构。"
        "规则明确、校验可重复时，人可主要核对差异和测试证据。遇到需求歧义、权限取舍或真实故障恢复，仍由人确定业务规则与验收标准。"
    )
    report.subheading("已验证的范围")
    report.table([
        ("证据", "验证范围"),
        ("PlantUML 制品", "8 份独立源文件通过 PlantUML 1.2025.4 语法检查，8 张 PNG 内嵌源码与对应源文件一致。"),
        ("设计模型", "23 个测试方法通过。包含三方竞争的 6 种顺序、4 类动作的 20 组提交前失败、截止边界、终态和重试。"),
        ("UI 设计与网页", "draw.io 检查主要导航链路。Chrome 验证预约与交付、审核、冲突提示、结果恢复、记录及统计等流程。Edge 验证本地打开、登录和预约。用户确认网页原型可进入下一步。"),
        ("后端验收", "实验三仍需在真实 PostgreSQL 和 HTTP 接口下验证并发、提交断线、权限校验、过期时限和查询性能。浏览器使用本地演示数据，两标签页检查的是顺序发生的旧状态冲突。"),
    ], 107)
    report.subheading("版本与材料索引")
    report.paragraph(
        "<b>lab2-ai-draft</b>　2026-11-11 20:16:22。AI 设计初版，恢复人工审查前的 UML 与解析。<br/>"
        "<b>lab2-reviewed-v2</b>　2026-11-12 00:19:34。人工审核修改版，收录修订后 UML、UI、网页和报告。"
    )
    report.paragraph(
        "两项 Git 时间为北京时间，分别对应首轮提交请求及网页验收。项目资料包括《UML 图解析》《UI 界面说明》"
        "《设计审查与修改记录》及 validation 目录。"
    )
    report.end_page()


def main():
    register_fonts()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    report = Report(OUTPUT)
    report.cover()
    add_scope(report)
    add_architecture(report)
    add_ui(report)
    add_ai_log(report)
    report.pdf.save()
    print(f"{report.page_number} pages, {report.figure_number} figures: {OUTPUT}")


if __name__ == "__main__":
    main()
