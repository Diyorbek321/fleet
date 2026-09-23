"""Render a period report as a spreadsheet.

Excel rather than PDF because of who opens it. The owner reads the summary on
the screen the report came from; the person who needs a *file* is the
accountant, and they need to sort it, filter it and paste it into their own
workbook. A PDF of the same numbers is a picture of data they would retype.

Values are written as numbers with a display format, never as pre-formatted
strings — a column of text that looks like money cannot be summed, which is the
first thing anyone does with it.
"""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.marker import DataPoint
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.services.period_reports import PeriodReport

_HEAD_FILL = PatternFill("solid", fgColor="1E3A8A")
_HEAD_FONT = Font(bold=True, color="FFFFFF", size=11)
_TITLE_FONT = Font(bold=True, size=15)
_SECTION_FONT = Font(bold=True, size=11, color="1E3A8A")
_TOTAL_FONT = Font(bold=True)
_BORDER = Border(bottom=Side(style="thin", color="D1D5DB"))

# One palette for every chart in the book, dark enough to read on a projector
# and on a phone screen — which is where most of these are first opened, since
# the workbook arrives as a Telegram attachment.
_NAVY = "1E3A8A"
_COST_COLORS = ("B45309", "0F766E", "7C3AED")  # fuel, driver, maintenance
_PROFIT_COLORS = ("1E3A8A", "B45309", "047857")  # revenue, cost, profit


def _labels(*, value: bool = False, percent: bool = False) -> DataLabelList:
    """Data labels with everything switched off except what was asked for.

    Every flag is set explicitly because the ones left unset are not off: a
    label built by only turning ``showPercent`` on came out of LibreOffice
    reading "Yoqilg'i; Column B; 161,901,964; 38%" — the category, the series'
    placeholder name, the value and the percentage, stacked over a slice two
    centimetres wide.
    """
    labels = DataLabelList()
    labels.showVal = value
    labels.showPercent = percent
    labels.showCatName = False
    labels.showSerName = False
    labels.showLegendKey = False
    labels.showBubbleSize = False
    return labels


def _style_bars(chart: BarChart, *, title: str, height: float, width: float,
                money: bool = True, values: bool = True) -> None:
    """House style for every bar chart: no gridlines, no legend, labelled bars.

    The legend is dropped on purpose — each of these charts carries a single
    series, so a legend would name the one thing already in the title.

    ``values`` turns the per-bar figures off for the charts that sit under
    their own table. A full sum figure is nine digits wide, and on the longest
    negative bar it reaches the axis and prints through the truck's name.
    Shortening those labels to millions would have been the better fix, but
    openpyxl drops a ``numFmt`` set on a label list — so the choice is the full
    number or none, and none is right where the exact figure is one row above.
    """
    chart.title = title
    chart.height = height
    chart.width = width
    chart.legend = None
    chart.y_axis.majorGridlines = None
    chart.dLbls = _labels(value=values)
    # Category names sit against the zero line by default, which for a chart
    # with negative bars prints the truck's name straight through its own bar.
    # "low" parks them at the left edge, clear of the plot either way.
    chart.x_axis.tickLblPos = "low"
    if money:
        # Axis ticks in sum run to nine digits and eat a third of the plot
        # width. The double comma is Excel's "scale by a thousand, twice".
        chart.y_axis.numFmt = '#,##0,,"M"'


# The sum has no minor unit in practice — nobody invoices in tiyin.
MONEY = "#,##0"
LITRES = "#,##0.0"
KM = "#,##0.0"
COUNT = "#,##0"


def _headers(ws, row: int, labels: list[str]) -> None:
    for col, label in enumerate(labels, start=1):
        cell = ws.cell(row=row, column=col, value=label)
        cell.fill = _HEAD_FILL
        cell.font = _HEAD_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _widths(ws, widths: list[int]) -> None:
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def _print_setup(ws) -> None:
    """Landscape, one page wide. These are read as often on a phone — where
    Telegram renders the attachment as a PDF — as in a spreadsheet, and the
    default portrait fit splits a twelve-column table down the middle."""
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def build_workbook(report: PeriodReport) -> bytes:
    wb = Workbook()

    # ── Сводка ───────────────────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Сводка"

    ws["A1"] = f"{report.organization} — {report.period.label}"
    ws["A1"].font = _TITLE_FONT
    ws["A2"] = f"Период: {report.period.start:%d.%m.%Y} – {report.period.end:%d.%m.%Y}"
    ws["A3"] = f"Сформирован: {report.generated_at:%d.%m.%Y %H:%M} UTC"
    ws["A3"].font = Font(color="6B7280", size=9)

    # Costs are written negative so the column adds up to the profit line on
    # its own. An accountant checking the arithmetic should not have to know
    # which rows to subtract.
    rows: list[tuple[str, object, str]] = [
        ("Доставлено рейсов", report.trips_delivered, COUNT),
        ("Рейсов в работе", report.trips_in_progress, COUNT),
        ("", "", ""),
        ("Выручка", report.revenue, MONEY),
        ("Расходы на топливо", -report.fuel_cost, MONEY),
        ("Расходы водителей", -report.expense_cost, MONEY),
        ("Техобслуживание", -report.maintenance_cost, MONEY),
        ("Итого расходы", -report.total_cost, MONEY),
        ("Чистая прибыль", report.profit, MONEY),
        ("Рентабельность, %", report.margin_pct, "#,##0.0"),
        ("", "", ""),
        ("Пройдено, км", report.distance_km, KM),
        ("Топливо, л", report.fuel_liters, LITRES),
        # Suppressed rather than shown with a footnote: a number in a cell
        # gets copied into someone else's workbook, and the caveat does not
        # travel with it.
        (
            "Расход, л/100км",
            report.l_per_100km if report.consumption_reliable else "недостаточно данных",
            "#,##0.0" if report.consumption_reliable else "General",
        ),
    ]

    row = 5
    for label, value, fmt in rows:
        if not label:
            row += 1
            continue
        ws.cell(row=row, column=1, value=label)
        cell = ws.cell(row=row, column=2, value=value)
        cell.number_format = fmt
        if label in ("Чистая прибыль", "Итого расходы"):
            ws.cell(row=row, column=1).font = _TOTAL_FONT
            cell.font = _TOTAL_FONT
        row += 1

    if not report.consumption_reliable:
        ws.cell(
            row=row + 1,
            column=1,
            value=(
                "Расход не показан: залитое топливо — это не сожжённое топливо, "
                "остаток в баке переходит на следующий период. На коротком периоде "
                "эта разница искажает результат. Смотрите месячный отчёт или страницу "
                "«Потери»: там каждая машина сравнивается с медианой по автопарку."
            ),
        ).font = Font(color="B45309", italic=True)
        row += 1

    if report.distance_partial:
        # Said on the sheet, not only in the API response: whoever opens the
        # file is the one who would otherwise divide fuel by a distance that
        # covers part of the period and read the answer as consumption.
        ws.cell(
            row=row + 1,
            column=1,
            value=(
                "Внимание: часть периода старше срока хранения GPS-данных. "
                "Пробег и л/100км неполные."
            ),
        ).font = Font(color="B45309", italic=True)
        row += 1

    # ── Chart sources ────────────────────────────────────────────────────────
    #
    # Written as visible mini-tables rather than hidden in some far column. A
    # chart whose numbers cannot be found on the sheet is a chart an accountant
    # does not trust, and these two tables are worth reading on their own: the
    # KPI block above carries the costs as negatives so the column sums to the
    # profit line, which is right for arithmetic and wrong for a pie.
    cost_top = row + 2
    ws.cell(row=cost_top, column=1, value="Структура расходов").font = _SECTION_FONT
    cost_rows = [
        ("Топливо", report.fuel_cost),
        ("Расходы водителей", report.expense_cost),
        ("Техобслуживание", report.maintenance_cost),
    ]
    for offset, (label, value) in enumerate(cost_rows, start=1):
        ws.cell(row=cost_top + offset, column=1, value=label)
        ws.cell(row=cost_top + offset, column=2, value=value).number_format = MONEY

    result_top = cost_top + len(cost_rows) + 2
    ws.cell(row=result_top, column=1, value="Финансовый результат").font = _SECTION_FONT
    result_rows = [
        ("Выручка", report.revenue),
        ("Итого расходы", report.total_cost),
        ("Чистая прибыль", report.profit),
    ]
    for offset, (label, value) in enumerate(result_rows, start=1):
        ws.cell(row=result_top + offset, column=1, value=label)
        ws.cell(row=result_top + offset, column=2, value=value).number_format = MONEY

    # ── Charts ───────────────────────────────────────────────────────────────
    if report.total_cost > 0:
        pie = PieChart()
        pie.title = "Структура расходов"
        pie.height, pie.width = 8.5, 12
        pie.add_data(
            Reference(ws, min_col=2, min_row=cost_top + 1, max_row=cost_top + len(cost_rows)),
            titles_from_data=False,
        )
        pie.set_categories(
            Reference(ws, min_col=1, min_row=cost_top + 1, max_row=cost_top + len(cost_rows))
        )
        pie.dataLabels = _labels(percent=True)
        # Slice colours are set per point: a pie is one series, so the series
        # colour would paint all three the same shade.
        for index, colour in enumerate(_COST_COLORS):
            point = DataPoint(idx=index)
            point.graphicalProperties.solidFill = colour
            pie.series[0].data_points.append(point)
        ws.add_chart(pie, "D5")

    bars = BarChart()
    bars.type = "col"
    _style_bars(bars, title="Выручка, расходы, прибыль", height=8.5, width=12)
    bars.add_data(
        Reference(ws, min_col=2, min_row=result_top + 1, max_row=result_top + len(result_rows)),
        titles_from_data=False,
    )
    bars.set_categories(
        Reference(ws, min_col=1, min_row=result_top + 1, max_row=result_top + len(result_rows))
    )
    for index, colour in enumerate(_PROFIT_COLORS):
        point = DataPoint(idx=index)
        point.graphicalProperties.solidFill = colour
        bars.series[0].data_points.append(point)
    # Beside the pie rather than under it: stacked, the second chart started
    # below the printable area and landed alone on page two.
    ws.add_chart(bars, "L5")

    _widths(ws, [30, 20])
    _print_setup(ws)

    # ── Машины ───────────────────────────────────────────────────────────────
    ws = wb.create_sheet("Машины")
    _headers(ws, 1, [
        "Машина", "Госномер", "Рейсы", "Выручка", "Топливо",
        "Расходы водителя", "Техобслуживание", "Итого расходы", "Прибыль",
        "Пробег, км", "Литры", "л/100км",
    ])
    for i, line in enumerate(report.trucks, start=2):
        values = [
            line.name, line.plate_number, line.trips, line.revenue, line.fuel_cost,
            line.expense_cost, line.maintenance_cost, line.total_cost, line.profit,
            line.distance_km, line.fuel_liters, line.l_per_100km,
        ]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=i, column=col, value=value)
            cell.border = _BORDER
            if col == 3:
                cell.number_format = COUNT
            elif col in (4, 5, 6, 7, 8, 9):
                cell.number_format = MONEY
            elif col == 10:
                cell.number_format = KM
            elif col in (11, 12):
                cell.number_format = LITRES
    ws.freeze_panes = "A2"
    last = len(report.trucks) + 1
    ws.auto_filter.ref = f"A1:L{max(2, last)}"
    _widths(ws, [22, 16, 8, 16, 16, 18, 16, 16, 16, 12, 12, 11])

    if report.trucks:
        # Anchored to the right of the table rather than below it, so both
        # charts are on screen while the rows are being read — and so sorting
        # or filtering the table does not push a chart out of view.
        chart_height = 0.9 * len(report.trucks) + 3
        profit = BarChart()
        profit.type = "bar"  # horizontal: truck names are long
        _style_bars(profit, title="Прибыль по машинам", height=chart_height, width=17,
                    values=False)
        profit.add_data(Reference(ws, min_col=9, min_row=1, max_row=last), titles_from_data=True)
        profit.set_categories(Reference(ws, min_col=1, min_row=2, max_row=last))
        profit.series[0].graphicalProperties.solidFill = _NAVY
        ws.add_chart(profit, f"A{last + 3}")

        # Consumption gets its own chart because it is the one column on this
        # sheet that is not money: a thirsty truck shows up here as a bar that
        # overshoots its neighbours long before it shows up in the profit
        # column, where a high-revenue run can hide it.
        if any(line.l_per_100km is not None for line in report.trucks):
            burn = BarChart()
            burn.type = "bar"
            _style_bars(burn, title="Расход, л/100км", height=chart_height, width=17,
                        money=False)
            burn.add_data(Reference(ws, min_col=12, min_row=1, max_row=last),
                          titles_from_data=True)
            burn.set_categories(Reference(ws, min_col=1, min_row=2, max_row=last))
            burn.series[0].graphicalProperties.solidFill = _COST_COLORS[0]
            ws.add_chart(burn, f"G{last + 3}")
    _print_setup(ws)

    # ── Водители ─────────────────────────────────────────────────────────────
    ws = wb.create_sheet("Водители")
    _headers(ws, 1, ["Водитель", "Рейсы", "Выручка", "Расходы"])
    for i, driver in enumerate(report.drivers, start=2):
        values = [driver.name, driver.trips, driver.revenue, driver.expense_cost]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=i, column=col, value=value)
            cell.border = _BORDER
            if col == 2:
                cell.number_format = COUNT
            elif col in (3, 4):
                cell.number_format = MONEY
    ws.freeze_panes = "A2"
    _widths(ws, [26, 8, 18, 18])

    if report.drivers:
        last = len(report.drivers) + 1
        earned = BarChart()
        earned.type = "bar"
        _style_bars(earned, title="Выручка по водителям",
                    height=0.9 * len(report.drivers) + 3, width=17, values=False)
        earned.add_data(Reference(ws, min_col=3, min_row=1, max_row=last), titles_from_data=True)
        earned.set_categories(Reference(ws, min_col=1, min_row=2, max_row=last))
        earned.series[0].graphicalProperties.solidFill = _NAVY
        ws.add_chart(earned, f"A{last + 3}")
    _print_setup(ws)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def filename_for(report: PeriodReport) -> str:
    """A filename that sorts chronologically in a folder full of them."""
    kind = "mesyachnyy" if report.period.kind == "month" else "nedelnyy"
    return f"otchet-{kind}-{report.period.start:%Y-%m-%d}.xlsx"
