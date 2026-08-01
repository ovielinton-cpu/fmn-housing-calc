import flet as ft
import flet_ads as fta
import json
import datetime
import traceback

async def build_ui(page: ft.Page):
    page.title = "Housing-Salary Calc"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.adaptive = True
    page.padding = 0

    DARK_TEXT = "#222222"
    PURPLE_TEXT = "#4B0082"

    BANNER_AD_UNIT_ID = {
        ft.PagePlatform.ANDROID: "ca-app-pub-3940256099942544/6300978111",
        ft.PagePlatform.IOS: "ca-app-pub-3940256099942544/2934735716",
    }

    def compute_paye_annual(taxable_annual: float) -> float:
        bands = [
            (800_000, 0.00),
            (3_000_000, 0.15),
            (12_000_000, 0.18),
            (25_000_000, 0.21),
            (50_000_000, 0.23),
            (float("inf"), 0.25),
        ]
        tax = 0.0
        lower = 0.0
        remaining = max(taxable_annual, 0.0)
        for upper, rate in bands:
            band_size = upper - lower
            if remaining <= 0:
                break
            taxed_in_band = min(remaining, band_size)
            tax += taxed_in_band * rate
            remaining -= taxed_in_band
            lower = upper
        return tax

    async def close_terms(e=None):
        try:
            await page.shared_preferences.set("terms_accepted", True)
            await check_name()
        except Exception as ex:
            show_error_screen(ex)

    def decline_terms(e=None):
        page.controls.clear()
        page.bgcolor = "#4B0082"
        page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text("Agreement Required", size=22, weight=ft.FontWeight.BOLD, color="white", text_align=ft.TextAlign.CENTER),
                        ft.Text(
                            "You must accept the Terms and Conditions to use this app. Please close and reopen the app if you'd like to review and accept them.",
                            size=15, color="white", text_align=ft.TextAlign.CENTER
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=15,
                ),
                padding=30,
                alignment=ft.Alignment(0, 0),
                expand=True,
            )
        )
        page.update()

    def show_terms_screen():
        scroll_hint = ft.Text(
            "⬇ Please scroll down to read the full agreement before continuing.",
            color="#FF3B30", size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER
        )

        agree_btn = ft.ElevatedButton(
            content=ft.Container(
                content=ft.Text("I Agree", weight=ft.FontWeight.BOLD, size=16, color="white"),
                padding=ft.Padding(left=10, right=10, top=6, bottom=6),
            ),
            on_click=close_terms,
            style=ft.ButtonStyle(bgcolor="#2E8B57"),
            width=280,
        )
        disagree_btn = ft.OutlinedButton(
            content=ft.Text("I Don't Agree", weight=ft.FontWeight.W_400, size=13, color="#C62828"),
            on_click=decline_terms,
            style=ft.ButtonStyle(side=ft.BorderSide(1, "#C62828")),
            width=280,
        )

        buttons_column = ft.Column([], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)

        def on_terms_scroll(e):
            if e.pixels >= (e.max_scroll_extent - 15):
                if not buttons_column.controls:
                    buttons_column.controls = [agree_btn, disagree_btn]
                    scroll_hint.visible = False
                    page.update()

        terms_listview = ft.ListView(
            controls=[
                ft.Text("Terms and Conditions", size=18, weight=ft.FontWeight.BOLD, color=PURPLE_TEXT),
                ft.Text(
                    "1. Purpose: This application is provided as a general tool to help staff of any organization estimate their housing upfront payments and salary breakdowns, based on figures you enter yourself.\n\n"
                    "2. Accuracy: All calculations, including PAYE tax estimates, are based on the Nigeria Tax Act 2025 as understood at the time of writing and are for guidance only. Verify against your organization's official payroll policy and current tax law.\n\n"
                    "3. Disclaimer: The developer is not responsible for any financial or tax decisions made based on these calculations. Please consult your HR department or a tax professional for official confirmation.\n\n"
                    "4. Privacy: No personal data or salary information is transmitted or shared externally by this application. Everything you enter and save stays on your device.",
                    color=DARK_TEXT,
                    size=14
                ),
            ],
            spacing=10,
            on_scroll=on_terms_scroll,
            expand=True,
        )

        page.controls.clear()
        page.bgcolor = "#4B0082"
        page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text("Welcome & Agreement", size=20, weight=ft.FontWeight.BOLD, color="white", text_align=ft.TextAlign.CENTER),
                        ft.Container(
                            content=terms_listview,
                            bgcolor="#FFFFFF",
                            border_radius=10,
                            padding=15,
                            expand=True,
                        ),
                        scroll_hint,
                        buttons_column,
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=15,
                    expand=True,
                ),
                padding=20,
                expand=True,
            )
        )
        page.update()

    greeting_name = ft.Text("Staff!", size=20, weight=ft.FontWeight.BOLD, color="white")

    def open_name_dialog(e=None):
        async def save_name(e):
            new_name = name_field.value
            greeting_name.value = f"{new_name}! 👋" if new_name else "Staff!"
            await page.shared_preferences.set("user_name", new_name)
            page.pop_dialog()
            page.update()

        name_field = ft.TextField(
            label="Your Name",
            value=greeting_name.value.split("!")[0] if "👋" in greeting_name.value else "",
            autofocus=True,
            bgcolor="#FFFFFF",
            color=PURPLE_TEXT,
            label_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD)
        )
        name_dialog = ft.AlertDialog(
            modal=True,
            bgcolor="#FFFFFF",
            title=ft.Text("Welcome!", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "Please enter your name so we can greet you personally.",
                            color=DARK_TEXT,
                            size=14
                        ),
                        name_field,
                    ],
                    tight=True,
                    spacing=15
                ),
                width=300,
                padding=10
            ),
            actions=[ft.TextButton("Save", on_click=save_name, style=ft.ButtonStyle(color=PURPLE_TEXT))],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(name_dialog)

    def show_error_screen(ex):
        page.controls.clear()
        page.bgcolor = "#4B0082"
        page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text("Startup Error", size=20, weight=ft.FontWeight.BOLD, color="white"),
                        ft.Text(str(ex), size=14, color="yellow", selectable=True),
                        ft.Divider(color="white"),
                        ft.Text(traceback.format_exc(), size=10, color="white", selectable=True),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
                padding=20,
                expand=True,
            )
        )
        page.update()

    async def check_name():
        try:
            existing_name = await page.shared_preferences.get("user_name")
            if not existing_name:
                open_name_dialog()
            await build_main_app()
        except Exception as ex:
            show_error_screen(ex)

    def field_with_caption(caption_text, field):
        return ft.Column(
            [
                ft.Text(caption_text, color="#FF3B30", weight=ft.FontWeight.BOLD, size=12),
                field,
            ],
            spacing=2,
            tight=True,
        )

    async def build_main_app():
        change_btn = ft.ElevatedButton(
            content=ft.Text("Change Name", weight=ft.FontWeight.BOLD, size=16, color="#4B0082"),
            on_click=open_name_dialog,
            style=ft.ButtonStyle(bgcolor="#FFD700")
        )

        greeting_row = ft.Container(
            content=ft.Row(
                controls=[ft.Text("Welcome back,", size=20, color="white"), greeting_name, change_btn],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=10,
                wrap=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border_radius=10,
            padding=ft.Padding(left=12, right=12, top=8, bottom=8),
        )

        logo_image = ft.Image(src="logo.png", width=90, height=90, fit=ft.BoxFit.CONTAIN)

        header_text = ft.Container(
            content=ft.Text(
                "Housing-Salary Calc", size=22, weight=ft.FontWeight.BOLD, color="white",
                text_align=ft.TextAlign.CENTER
            ),
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border_radius=10,
            padding=ft.Padding(left=16, right=16, top=8, bottom=8),
        )

        header_container = ft.Container(
            content=ft.Column(
                controls=[logo_image, header_text],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8
            ),
            padding=20,
            width=None,
        )

        try:
            saved_name = await page.shared_preferences.get("user_name")
            if saved_name:
                greeting_name.value = f"{saved_name}! 👋"
        except Exception:
            pass

        async def load_saved(key, default=""):
            try:
                val = await page.shared_preferences.get(key)
                return val if val is not None else default
            except Exception:
                return default

        # ---------- HOUSING UPFRONT TAB ----------
        last_org = await load_saved("last_org", "")
        last_salary = await load_saved("last_salary", "")
        last_increment_label = await load_saved("last_increment_label", "Salary Increment")
        last_increment_pct = await load_saved("last_increment_pct", "0")
        last_rate_pct = await load_saved("last_rate_pct", "40")

        async def on_org_change(e):
            await page.shared_preferences.set("last_org", org_input.value)

        async def on_salary_change(e):
            await page.shared_preferences.set("last_salary", salary_input.value)

        async def on_increment_label_change(e):
            await page.shared_preferences.set("last_increment_label", increment_label_input.value)

        async def on_increment_change(e):
            await page.shared_preferences.set("last_increment_pct", increment_input.value)

        async def on_rate_change(e):
            await page.shared_preferences.set("last_rate_pct", rate_input.value)

        org_input = ft.TextField(
            value=last_org, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), on_change=on_org_change
        )
        salary_input = ft.TextField(
            value=last_salary, keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT, color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), on_change=on_salary_change
        )
        increment_label_input = ft.TextField(
            value=last_increment_label, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), on_change=on_increment_label_change
        )
        increment_input = ft.TextField(
            value=last_increment_pct, keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT, color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), on_change=on_increment_change
        )
        rate_input = ft.TextField(
            value=last_rate_pct, keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT, color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), on_change=on_rate_change
        )

        result_upfront = ft.Text(spans=[ft.TextSpan("Upfront: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=18)
        result_basic = ft.Text(spans=[ft.TextSpan("New Basic: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        result_increment = ft.Text(spans=[ft.TextSpan("Increment Addition: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        result_total = ft.Text(spans=[ft.TextSpan("Annual Salary: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)

        def on_calculate_click(e):
            try:
                salary = float(salary_input.value)
                increment_pct = float(increment_input.value)
                rate_pct = float(rate_input.value)
                increment_name = increment_label_input.value.strip() or "Increment"

                increment_amount = salary * (increment_pct / 100.0)
                new_basic = salary + increment_amount
                annual_salary = new_basic * 12.0
                upfront_amount = annual_salary * (rate_pct / 100.0)

                result_upfront.spans[1].text = f"₦{upfront_amount:,.2f}"
                result_basic.spans[1].text = f"₦{new_basic:,.2f}"
                result_increment.spans[0].text = f"{increment_name} Addition: "
                result_increment.spans[1].text = f"₦{increment_amount:,.2f}"
                result_total.spans[1].text = f"₦{annual_salary:,.2f}"
                page.update()
            except ValueError:
                result_upfront.spans[1].text = "Invalid Input"
                page.update()

        calc_btn = ft.ElevatedButton("Calculate Upfront", on_click=on_calculate_click, style=ft.ButtonStyle(bgcolor="#FFD700", color="#4B0082", text_style=ft.TextStyle(weight=ft.FontWeight.BOLD)))

        housing_form = ft.Container(
            content=ft.Column(
                controls=[
                    field_with_caption("Company / Organization Name (optional)", org_input),
                    field_with_caption("Basic Salary (₦)", salary_input),
                    field_with_caption("Increment Name (e.g. NDIC)", increment_label_input),
                    field_with_caption("Increment (%)", increment_input),
                    field_with_caption("Housing Upfront Rate (%)", rate_input),
                    calc_btn
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=30, tight=True
            ),
            padding=20, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.with_opacity(0.20, ft.Colors.BLACK))
        )

        housing_results = ft.Container(
            content=ft.Column([result_upfront, ft.Divider(height=1, color="#4B0082"), result_basic, result_increment, result_total], spacing=8, tight=True),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border=ft.Border(ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700")),
            shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK))
        )

        housing_tab_content = ft.Column(
            controls=[housing_form, ft.Container(height=10), housing_results],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

        # ---------- SALARY MANAGEMENT TAB ----------
        sm_last_basic = await load_saved("sm_basic", "")
        sm_last_housing = await load_saved("sm_housing", "")
        sm_last_transport = await load_saved("sm_transport", "")
        sm_last_other = await load_saved("sm_other", "")
        sm_last_rent = await load_saved("sm_rent", "")

        async def sm_on_basic_change(e):
            await page.shared_preferences.set("sm_basic", sm_basic_input.value)

        async def sm_on_housing_change(e):
            await page.shared_preferences.set("sm_housing", sm_housing_input.value)

        async def sm_on_transport_change(e):
            await page.shared_preferences.set("sm_transport", sm_transport_input.value)

        async def sm_on_other_change(e):
            await page.shared_preferences.set("sm_other", sm_other_input.value)

        async def sm_on_rent_change(e):
            await page.shared_preferences.set("sm_rent", sm_rent_input.value)

        sm_basic_input = ft.TextField(
            value=sm_last_basic,
            keyboard_type=ft.KeyboardType.NUMBER,
            bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT,
            color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            on_change=sm_on_basic_change
        )

        sm_housing_input = ft.TextField(
            value=sm_last_housing,
            keyboard_type=ft.KeyboardType.NUMBER,
            bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT,
            color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            on_change=sm_on_housing_change
        )

        sm_transport_input = ft.TextField(
            value=sm_last_transport,
            keyboard_type=ft.KeyboardType.NUMBER,
            bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT,
            color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            on_change=sm_on_transport_change
        )

        sm_other_input = ft.TextField(
            value=sm_last_other,
            keyboard_type=ft.KeyboardType.NUMBER,
            bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT,
            color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            on_change=sm_on_other_change
        )

        sm_rent_input = ft.TextField(
            value=sm_last_rent,
            keyboard_type=ft.KeyboardType.NUMBER,
            bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT,
            color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            on_change=sm_on_rent_change
        )

        sm_result_gross = ft.Text(spans=[ft.TextSpan("Gross Monthly: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=16)
        sm_result_tax = ft.Text(spans=[ft.TextSpan("Monthly PAYE Tax: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="red", weight=ft.FontWeight.BOLD))], size=14)
        sm_result_net = ft.Text(spans=[ft.TextSpan("Net Monthly: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=16)
        sm_result_rent_ded = ft.Text(spans=[ft.TextSpan("Rent Deduction: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="red", weight=ft.FontWeight.BOLD))], size=14)
        sm_result_final = ft.Text(spans=[ft.TextSpan("Net After Rent: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=16)

        def on_sm_calculate(e):
            try:
                basic = float(sm_basic_input.value) if sm_basic_input.value else 0
                housing = float(sm_housing_input.value) if sm_housing_input.value else 0
                transport = float(sm_transport_input.value) if sm_transport_input.value else 0
                other = float(sm_other_input.value) if sm_other_input.value else 0
                rent = float(sm_rent_input.value) if sm_rent_input.value else 0

                gross_monthly = basic + housing + transport + other
                annual_tax = compute_paye_annual(gross_monthly * 12)
                monthly_tax = annual_tax / 12
                net_monthly = gross_monthly - monthly_tax
                net_after_rent = net_monthly - rent

                sm_result_gross.spans[1].text = f"₦{gross_monthly:,.2f}"
                sm_result_tax.spans[1].text = f"₦{monthly_tax:,.2f}"
                sm_result_net.spans[1].text = f"₦{net_monthly:,.2f}"
                sm_result_rent_ded.spans[1].text = f"₦{rent:,.2f}"
                sm_result_final.spans[1].text = f"₦{net_after_rent:,.2f}"
                page.update()
            except ValueError:
                for res in [sm_result_gross, sm_result_tax, sm_result_net, sm_result_rent_ded, sm_result_final]:
                    res.spans[1].text = "Invalid Input"
                page.update()

        sm_calc_btn = ft.ElevatedButton("Calculate Monthly Breakdown", on_click=on_sm_calculate, style=ft.ButtonStyle(bgcolor="#FFD700", color="#4B0082", text_style=ft.TextStyle(weight=ft.FontWeight.BOLD)))

        sm_form = ft.Container(
            content=ft.Column(
                controls=[
                    field_with_caption("Basic Salary (₦)", sm_basic_input),
                    field_with_caption("Housing Allowance (₦)", sm_housing_input),
                    field_with_caption("Transport Allowance (₦)", sm_transport_input),
                    field_with_caption("Other Allowances (₦)", sm_other_input),
                    field_with_caption("Rent Deduction (₦)", sm_rent_input),
                    sm_calc_btn,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=30, tight=True
            ),
            padding=20, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.with_opacity(0.20, ft.Colors.BLACK))
        )

        sm_results = ft.Container(
            content=ft.Column(
                [sm_result_gross, ft.Divider(height=1, color="#4B0082"),
                 sm_result_tax, sm_result_net,
                 ft.Divider(height=1, color="#4B0082"),
                 sm_result_rent_ded, sm_result_final],
                spacing=8, tight=True
            ),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border=ft.Border(ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700")),
            shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK))
        )

        salary_tab_content = ft.Column(
            controls=[sm_form, ft.Container(height=10), sm_results],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

        # ---------- MONEY TRACKER TAB ----------
        async def load_transactions():
            try:
                data = await page.shared_preferences.get("transactions")
                if data:
                    return json.loads(data)
                return []
            except:
                return []

        async def save_transactions(transactions):
            await page.shared_preferences.set("transactions", json.dumps(transactions))

        tracker_description = ft.TextField(
            label="Note (optional)",
            bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT,
            color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            width=200,
        )
        tracker_amount = ft.TextField(
            label="Amount (₦)",
            keyboard_type=ft.KeyboardType.NUMBER,
            bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT,
            color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            width=150,
        )
        tracker_type_dropdown = ft.Dropdown(
            label="Type",
            options=[
                ft.dropdown.Option("Income"),
                ft.dropdown.Option("Expense"),
            ],
            value="Income",
            bgcolor="#FFFFFF",
            border_color=PURPLE_TEXT,
            color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            width=150,
        )

        summary_income = ft.Text("Income: ₦0", size=14, color="green", weight=ft.FontWeight.BOLD)
        summary_expense = ft.Text("Expense: ₦0", size=14, color="red", weight=ft.FontWeight.BOLD)
        summary_net = ft.Text("Net: ₦0", size=14, color="white", weight=ft.FontWeight.BOLD)
        summary_row = ft.Row(
            controls=[summary_income, summary_expense, summary_net],
            alignment=ft.MainAxisAlignment.SPACE_AROUND,
            spacing=10,
        )

        # ---------- CUSTOM BAR CHART (works without ft.BarChart) ----------
        chart_income_bar = ft.Container(
            height=20,
            bgcolor=ft.colors.GREEN,
            border_radius=5,
        )
        chart_expense_bar = ft.Container(
            height=20,
            bgcolor=ft.colors.RED,
            border_radius=5,
        )
        chart_income_label = ft.Text("Income: ₦0", size=12, color="green")
        chart_expense_label = ft.Text("Expense: ₦0", size=12, color="red")

        chart_row = ft.Row(
            controls=[
                ft.Column(
                    [
                        chart_income_label,
                        ft.Row([chart_income_bar], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ],
                    spacing=5,
                    expand=True,
                ),
                ft.Column(
                    [
                        chart_expense_label,
                        ft.Row([chart_expense_bar], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ],
                    spacing=5,
                    expand=True,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_EVENLY,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        chart_container = ft.Container(
            content=chart_row,
            padding=10,
            bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.WHITE),
            border_radius=10,
            height=120,
        )

        tracker_list = ft.ListView(expand=True, spacing=5, padding=5)

        async def refresh_tracker():
            transactions = await load_transactions()
            now = datetime.datetime.now()
            current_month = now.month
            current_year = now.year
            month_trans = []
            for t in transactions:
                try:
                    dt = datetime.datetime.fromisoformat(t.get("date", ""))
                    if dt.month == current_month and dt.year == current_year:
                        month_trans.append(t)
                except:
                    pass

            total_income = sum(t["amount"] for t in month_trans if t["type"] == "Income")
            total_expense = sum(t["amount"] for t in month_trans if t["type"] == "Expense")
            net = total_income - total_expense

            summary_income.value = f"Income: ₦{total_income:,.2f}"
            summary_expense.value = f"Expense: ₦{total_expense:,.2f}"
            summary_net.value = f"Net: ₦{net:,.2f}"
            summary_net.color = "green" if net >= 0 else "red"

            # Update custom chart bars
            max_val = max(total_income, total_expense, 1000)
            income_width = (total_income / max_val) * 200  # max width ~200px
            expense_width = (total_expense / max_val) * 200
            chart_income_bar.width = max(income_width, 5)
            chart_expense_bar.width = max(expense_width, 5)
            chart_income_label.value = f"Income: ₦{total_income:,.2f}"
            chart_expense_label.value = f"Expense: ₦{total_expense:,.2f}"

            # Recent transactions (last 15, newest first)
            sorted_trans = sorted(transactions, key=lambda t: t.get("date", ""), reverse=True)
            recent = sorted_trans[:15]

            tracker_list.controls.clear()
            for t in recent:
                amt = t.get("amount", 0)
                ttype = t.get("type", "")
                desc = t.get("description", "")
                try:
                    dt = datetime.datetime.fromisoformat(t.get("date", ""))
                    date_str = dt.strftime("%d %b %H:%M")
                except:
                    date_str = ""

                row = ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Column(
                                [
                                    ft.Text(desc or "(no note)", size=14, weight=ft.FontWeight.BOLD, color="white"),
                                    ft.Text(f"{ttype} • ₦{amt:,.2f} • {date_str}", size=12, color="#FFD700"),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.icons.DELETE_OUTLINE,
                                icon_color="red",
                                on_click=lambda e, tid=t.get("id"): delete_transaction(tid),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    bgcolor=ft.Colors.with_opacity(0.3, ft.Colors.WHITE),
                    border_radius=5,
                    padding=8,
                )
                tracker_list.controls.append(row)

            page.update()

        async def delete_transaction(tid):
            transactions = await load_transactions()
            transactions = [t for t in transactions if t.get("id") != tid]
            await save_transactions(transactions)
            await refresh_tracker()

        async def add_transaction(e):
            desc = tracker_description.value.strip()
            amt_str = tracker_amount.value.strip()
            ttype = tracker_type_dropdown.value
            if not desc:
                tracker_description.error_text = "Note is optional, but please add a description"
                page.update()
                return
            if not amt_str:
                tracker_amount.error_text = "Amount required"
                page.update()
                return
            try:
                amt = float(amt_str)
                if amt <= 0:
                    tracker_amount.error_text = "Amount must be positive"
                    page.update()
                    return
            except ValueError:
                tracker_amount.error_text = "Invalid number"
                page.update()
                return

            tracker_description.error_text = None
            tracker_amount.error_text = None

            transactions = await load_transactions()
            new_id = max([t.get("id", 0) for t in transactions], default=0) + 1
            transactions.append({
                "id": new_id,
                "description": desc,
                "amount": amt,
                "type": ttype,
                "date": datetime.datetime.now().isoformat(),
            })
            await save_transactions(transactions)
            tracker_description.value = ""
            tracker_amount.value = ""
            tracker_type_dropdown.value = "Income"
            await refresh_tracker()

        add_btn = ft.ElevatedButton(
            "Add Transaction",
            on_click=add_transaction,
            style=ft.ButtonStyle(bgcolor="#FFD700", color="#4B0082", text_style=ft.TextStyle(weight=ft.FontWeight.BOLD))
        )

        tracker_input_row = ft.Row(
            controls=[
                tracker_description,
                tracker_amount,
                tracker_type_dropdown,
                add_btn,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            wrap=True,
            spacing=10,
        )

        tracker_tab_content = ft.Column(
            controls=[
                tracker_input_row,
                ft.Divider(height=1, color="#FFD700"),
                summary_row,
                chart_container,   # custom chart
                ft.Divider(height=1, color="#FFD700"),
                ft.Text("Recent Transactions", size=14, weight=ft.FontWeight.BOLD, color="white"),
                ft.Container(
                    content=tracker_list,
                    expand=True,
                    bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.WHITE),
                    border_radius=10,
                    padding=5,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
            expand=True,
        )

        # ---------- BUILD TABS ----------
        tabs = ft.Tabs(
            selected_index=0,
            tabs=[
                ft.Tab("Housing Upfront", content=ft.Container(content=housing_tab_content, padding=ft.Padding(top=15, left=0, right=0, bottom=0))),
                ft.Tab("Salary Management", content=ft.Container(content=salary_tab_content, padding=ft.Padding(top=15, left=0, right=0, bottom=0))),
                ft.Tab("Money Tracker", content=ft.Container(content=tracker_tab_content, padding=ft.Padding(top=15, left=0, right=0, bottom=0))),
            ],
            expand=True,
        )

        page.controls.clear()
        page.bgcolor = "#4B0082"
        page.add(
            header_container,
            greeting_row,
            tabs,
        )

        await refresh_tracker()
        page.update()

    # ---------- STARTUP ----------
    try:
        terms_accepted = await page.shared_preferences.get("terms_accepted")
        if not terms_accepted:
            show_terms_screen()
        else:
            await check_name()
    except Exception as ex:
        show_error_screen(ex)


if __name__ == "__main__":
    ft.app(target=build_ui, view=ft.AppView.WEB_BROWSER)
