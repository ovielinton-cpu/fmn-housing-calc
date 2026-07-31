import flet as ft
import flet_ads as fta
import json
import datetime

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

    # ==================================================================
    # NIGERIA PAYE TAX (Nigeria Tax Act 2025, effective 1 Jan 2026)
    # ==================================================================
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

    # ==================================================================
    # TERMS AND CONDITIONS (full-page, scroll-gated)
    # ==================================================================
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

    # ==================================================================
    # NAME PROMPT
    # ==================================================================
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
        import traceback
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

    # ==================================================================
    # SHARED UI HELPER
    # ==================================================================
    def field_with_caption(caption_text, field):
        return ft.Column(
            [
                ft.Text(caption_text, color="#FF3B30", weight=ft.FontWeight.BOLD, size=12),
                field,
            ],
            spacing=2,
            tight=True,
        )

    # ==================================================================
    # MAIN APP (Housing Upfront tab + Salary Management tab)
    # ==================================================================
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
                return val if val else default
            except Exception:
                return default

        # -------------------- HOUSING UPFRONT TAB --------------------
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

        # -------------------- SALARY MANAGEMENT TAB --------------------
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

        sm_basic_input = ft.TextField(value=sm_last_basic, keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), on_change=sm_on_basic_change)
        sm_housing_input = ft.TextField(value=sm_last_housing, keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), on_change=sm_on_housing_change)
        sm_transport_input = ft.TextField(value=sm_last_transport, keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), on_change=sm_on_transport_change)
        sm_other_input = ft.TextField(value=sm_last_other, keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), on_change=sm_on_other_change)
        sm_rent_input = ft.TextField(value=sm_last_rent, keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD), on_change=sm_on_rent_change)

        sm_result_gross = ft.Text(spans=[ft.TextSpan("Gross Pay (Monthly): ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=16)
        sm_result_pension = ft.Text(spans=[ft.TextSpan("Pension (8%): ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        sm_result_nhf = ft.Text(spans=[ft.TextSpan("NHF (2.5%): ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        sm_result_paye = ft.Text(spans=[ft.TextSpan("PAYE Tax: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        sm_result_net = ft.Text(spans=[ft.TextSpan("Net Pay (Monthly): ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=18)
        sm_status_text = ft.Text("", color="white", size=12, text_align=ft.TextAlign.CENTER)

        last_sm_result = {}

        def sm_on_calculate_click(e):
            try:
                basic = float(sm_basic_input.value or 0)
                housing = float(sm_housing_input.value or 0)
                transport = float(sm_transport_input.value or 0)
                other = float(sm_other_input.value or 0)
                annual_rent = float(sm_rent_input.value or 0)

                gross_monthly = basic + housing + transport + other
                gross_annual = gross_monthly * 12.0

                pension_basis_annual = (basic + housing + transport) * 12.0
                pension_annual = pension_basis_annual * 0.08
                nhf_annual = (basic * 12.0) * 0.025
                rent_relief = min(annual_rent * 0.20, 500_000.0) if annual_rent > 0 else 0.0

                taxable_annual = max(gross_annual - pension_annual - nhf_annual - rent_relief, 0.0)
                paye_annual = compute_paye_annual(taxable_annual)
                paye_monthly = paye_annual / 12.0

                total_deductions_monthly = (pension_annual / 12.0) + (nhf_annual / 12.0) + paye_monthly
                net_monthly = gross_monthly - total_deductions_monthly

                sm_result_gross.spans[1].text = f"₦{gross_monthly:,.2f}"
                sm_result_pension.spans[1].text = f"₦{pension_annual/12.0:,.2f}"
                sm_result_nhf.spans[1].text = f"₦{nhf_annual/12.0:,.2f}"
                sm_result_paye.spans[1].text = f"₦{paye_monthly:,.2f}"
                sm_result_net.spans[1].text = f"₦{net_monthly:,.2f}"

                last_sm_result.clear()
                last_sm_result.update({
                    "basic": basic, "housing": housing, "transport": transport, "other": other,
                    "gross_monthly": gross_monthly, "pension_monthly": pension_annual/12.0,
                    "nhf_monthly": nhf_annual/12.0, "paye_monthly": paye_monthly, "net_monthly": net_monthly,
                })
                sm_status_text.value = ""
                page.update()
            except ValueError:
                sm_result_gross.spans[1].text = "Invalid Input"
                page.update()

        async def sm_on_save_click(e):
            if not last_sm_result:
                sm_status_text.value = "Please calculate first before saving."
                page.update()
                return
            entry = dict(last_sm_result)
            entry["date"] = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
            try:
                raw = await page.shared_preferences.get("salary_history")
                history = json.loads(raw) if raw else []
            except Exception:
                history = []
            history.insert(0, entry)
            history = history[:20]
            await page.shared_preferences.set("salary_history", json.dumps(history))
            sm_status_text.value = "Saved to history."
            page.update()

        def sm_on_share_click(e):
            if not last_sm_result:
                sm_status_text.value = "Please calculate first before sharing."
                page.update()
                return
            r = last_sm_result
            summary = (
                "Salary Breakdown\n"
                f"Basic Salary: ₦{r['basic']:,.2f}\n"
                f"Housing Allowance: ₦{r['housing']:,.2f}\n"
                f"Transport Allowance: ₦{r['transport']:,.2f}\n"
                f"Other Allowances: ₦{r['other']:,.2f}\n"
                f"Gross Pay (Monthly): ₦{r['gross_monthly']:,.2f}\n"
                f"Pension (8%): ₦{r['pension_monthly']:,.2f}\n"
                f"NHF (2.5%): ₦{r['nhf_monthly']:,.2f}\n"
                f"PAYE Tax: ₦{r['paye_monthly']:,.2f}\n"
                f"Net Pay (Monthly): ₦{r['net_monthly']:,.2f}"
            )
            try:
                page.set_clipboard(summary)
                sm_status_text.value = "Copied to clipboard! Paste it in WhatsApp, Email, etc."
            except Exception:
                sm_status_text.value = "Could not copy automatically."
            page.update()

        async def sm_show_history(e):
            try:
                raw = await page.shared_preferences.get("salary_history")
                history = json.loads(raw) if raw else []
            except Exception:
                history = []

            if not history:
                rows = [ft.Text("No saved calculations yet.", color=DARK_TEXT)]
            else:
                rows = []
                for item in history:
                    rows.append(
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Text(item.get("date", ""), size=12, color="#666666"),
                                    ft.Text(f"Net Pay: ₦{item.get('net_monthly', 0):,.2f}", weight=ft.FontWeight.BOLD, color=PURPLE_TEXT),
                                    ft.Text(f"Gross: ₦{item.get('gross_monthly', 0):,.2f}  |  PAYE: ₦{item.get('paye_monthly', 0):,.2f}", size=12, color=DARK_TEXT),
                                ],
                                spacing=2,
                            ),
                            padding=10,
                            border=ft.Border(ft.BorderSide(1, "#DDDDDD"), ft.BorderSide(1, "#DDDDDD"), ft.BorderSide(1, "#DDDDDD"), ft.BorderSide(1, "#DDDDDD")),
                            border_radius=8,
                        )
                    )

            async def clear_history(e):
                await page.shared_preferences.set("salary_history", json.dumps([]))
                page.pop_dialog()

            history_dialog = ft.AlertDialog(
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text("Saved Calculations", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.ListView(controls=rows, spacing=10),
                    width=320,
                    height=350,
                ),
                actions=[
                    ft.TextButton("Clear History", on_click=clear_history, style=ft.ButtonStyle(color="#C62828")),
                    ft.TextButton("Close", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(history_dialog)

        sm_calc_btn = ft.ElevatedButton("Calculate Payslip", on_click=sm_on_calculate_click, style=ft.ButtonStyle(bgcolor="#FFD700", color="#4B0082", text_style=ft.TextStyle(weight=ft.FontWeight.BOLD)))
        sm_save_btn = ft.OutlinedButton(content=ft.Text("Save", color="white", weight=ft.FontWeight.BOLD), on_click=sm_on_save_click, style=ft.ButtonStyle(side=ft.BorderSide(1, "white")))
        sm_history_btn = ft.OutlinedButton(content=ft.Text("History", color="white", weight=ft.FontWeight.BOLD), on_click=sm_show_history, style=ft.ButtonStyle(side=ft.BorderSide(1, "white")))
        sm_share_btn = ft.OutlinedButton(content=ft.Text("Share", color="white", weight=ft.FontWeight.BOLD), on_click=sm_on_share_click, style=ft.ButtonStyle(side=ft.BorderSide(1, "white")))

        sm_form = ft.Container(
            content=ft.Column(
                controls=[
                    field_with_caption("Basic Salary (₦, monthly)", sm_basic_input),
                    field_with_caption("Housing Allowance (₦, monthly)", sm_housing_input),
                    field_with_caption("Transport Allowance (₦, monthly)", sm_transport_input),
                    field_with_caption("Other Allowances (₦, monthly)", sm_other_input),
                    field_with_caption("Annual Rent Paid (₦, optional - for rent relief)", sm_rent_input),
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
                [
                    sm_result_gross, ft.Divider(height=1, color="#4B0082"),
                    sm_result_pension, sm_result_nhf, sm_result_paye,
                    ft.Divider(height=1, color="#4B0082"),
                    sm_result_net,
                    ft.Row([sm_save_btn, sm_history_btn, sm_share_btn], alignment=ft.MainAxisAlignment.CENTER, spacing=8, wrap=True),
                    sm_status_text,
                ],
                spacing=8, tight=True
            ),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border=ft.Border(ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700")),
            shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK))
        )

        sm_note = ft.Text(
            "Based on Nigeria Tax Act 2025 (effective Jan 2026): first ₦800k/year tax-free, Pension 8% of Basic+Housing+Transport, NHF 2.5% of Basic. For guidance only — confirm with your HR/tax professional.",
            size=11, color="white", text_align=ft.TextAlign.CENTER, italic=True
        )

        salary_tab_content = ft.Column(
            controls=[sm_form, ft.Container(height=10), sm_results, sm_note],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

        # -------------------- MONEY TRACKER TAB --------------------
        async def load_transactions():
            try:
                raw = await page.shared_preferences.get("money_transactions")
                return json.loads(raw) if raw else []
            except Exception:
                return []

        async def save_transactions(transactions):
            await page.shared_preferences.set("money_transactions", json.dumps(transactions))

        mt_type_dropdown = ft.Dropdown(
            options=[
                ft.dropdown.Option(key="income", text="Income", content=ft.Text("Income", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD)),
                ft.dropdown.Option(key="expense", text="Expense", content=ft.Text("Expense", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD)),
            ],
            value="income",
            bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        )
        mt_amount_input = ft.TextField(keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD))
        mt_note_input = ft.TextField(bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD))
        mt_status_text = ft.Text("", color="white", size=12, text_align=ft.TextAlign.CENTER)

        mt_summary_income = ft.Text(spans=[ft.TextSpan("This Month Income: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        mt_summary_expense = ft.Text(spans=[ft.TextSpan("This Month Expense: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        mt_summary_net = ft.Text(spans=[ft.TextSpan("Net (This Month): ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=18)

        mt_chart_container = ft.Container(padding=10, height=220, alignment=ft.Alignment(0, 0))
        mt_transactions_list_view = ft.ListView(controls=[], spacing=8, height=220)

        async def refresh_money_ui():
            transactions = await load_transactions()
            today = datetime.date.today()
            month_income = 0.0
            month_expense = 0.0
            for t in transactions:
                try:
                    d = datetime.date.fromisoformat(t["date"])
                except Exception:
                    continue
                if d.year == today.year and d.month == today.month:
                    if t["type"] == "income":
                        month_income += t["amount"]
                    else:
                        month_expense += t["amount"]
            net = month_income - month_expense

            mt_summary_income.spans[1].text = f"₦{month_income:,.2f}"
            mt_summary_expense.spans[1].text = f"₦{month_expense:,.2f}"
            mt_summary_net.spans[1].text = f"₦{net:,.2f}"

            max_val = max(month_income, month_expense, 1.0)
            mt_chart_container.content = ft.BarChart(
                bar_groups=[
                    ft.BarChartGroup(x=0, bar_rods=[ft.BarChartRod(from_y=0, to_y=month_income, width=40, color="#2E8B57")]),
                    ft.BarChartGroup(x=1, bar_rods=[ft.BarChartRod(from_y=0, to_y=month_expense, width=40, color="#C62828")]),
                ],
                bottom_axis=ft.ChartAxis(
                    labels=[
                        ft.ChartAxisLabel(value=0, label=ft.Text("Income", size=12, color="white", weight=ft.FontWeight.BOLD)),
                        ft.ChartAxisLabel(value=1, label=ft.Text("Expense", size=12, color="white", weight=ft.FontWeight.BOLD)),
                    ],
                    labels_size=30,
                ),
                left_axis=ft.ChartAxis(labels_size=40),
                max_y=max_val * 1.2,
                interactive=True,
                expand=True,
            )

            def make_delete(index):
                async def _delete(e):
                    full = await load_transactions()
                    if 0 <= index < len(full):
                        del full[index]
                    await save_transactions(full)
                    await refresh_money_ui()
                    page.update()
                return _delete

            recent = transactions[:15]
            rows = []
            for idx, t in enumerate(recent):
                color = "#2E8B57" if t["type"] == "income" else "#C62828"
                sign = "+" if t["type"] == "income" else "-"
                rows.append(
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(t.get("note", "") or t["type"].capitalize(), weight=ft.FontWeight.BOLD, color=PURPLE_TEXT, size=13),
                                    ft.Text(t.get("date", ""), size=10, color="#666666"),
                                ],
                                spacing=0, expand=True,
                            ),
                            ft.Text(f"{sign}₦{t['amount']:,.2f}", color=color, weight=ft.FontWeight.BOLD),
                            ft.IconButton(icon=ft.Icons.CLOSE, icon_color="#C62828", icon_size=16, on_click=make_delete(idx)),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )
                )
            mt_transactions_list_view.controls = rows if rows else [ft.Text("No transactions yet.", color=DARK_TEXT)]
            page.update()

        async def mt_on_add_click(e):
            try:
                amount = float(mt_amount_input.value)
            except (ValueError, TypeError):
                mt_status_text.value = "Please enter a valid amount."
                page.update()
                return
            entry = {
                "type": mt_type_dropdown.value or "income",
                "amount": amount,
                "note": (mt_note_input.value or "").strip(),
                "date": datetime.date.today().isoformat(),
            }
            transactions = await load_transactions()
            transactions.insert(0, entry)
            transactions = transactions[:200]
            await save_transactions(transactions)
            mt_amount_input.value = ""
            mt_note_input.value = ""
            mt_status_text.value = "Transaction added."
            await refresh_money_ui()
            page.update()

        mt_add_btn = ft.ElevatedButton("Add Transaction", on_click=mt_on_add_click, style=ft.ButtonStyle(bgcolor="#FFD700", color="#4B0082", text_style=ft.TextStyle(weight=ft.FontWeight.BOLD)))

        mt_form = ft.Container(
            content=ft.Column(
                controls=[
                    field_with_caption("Type", mt_type_dropdown),
                    field_with_caption("Amount (₦)", mt_amount_input),
                    field_with_caption("Note (optional)", mt_note_input),
                    mt_add_btn,
                    mt_status_text,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=20, tight=True
            ),
            padding=20, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.with_opacity(0.20, ft.Colors.BLACK))
        )

        mt_summary_container = ft.Container(
            content=ft.Column([mt_summary_income, mt_summary_expense, ft.Divider(height=1, color="#4B0082"), mt_summary_net], spacing=8, tight=True),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border=ft.Border(ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700")),
            shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK))
        )

        mt_chart_card = ft.Container(
            content=mt_chart_container,
            padding=10, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        )

        mt_list_card = ft.Container(
            content=ft.Column(
                [ft.Text("Recent Transactions", color="white", weight=ft.FontWeight.BOLD, size=14), mt_transactions_list_view],
                spacing=8,
            ),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        )

        await refresh_money_ui()

        money_tab_content = ft.Column(
            controls=[mt_form, ft.Container(height=10), mt_summary_container, ft.Container(height=10), mt_chart_card, ft.Container(height=10), mt_list_card],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

        # -------------------- TABS --------------------
        tabs = ft.Tabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Housing Upfront", content=ft.Container(content=housing_tab_content, padding=ft.Padding(top=15, left=0, right=0, bottom=0))),
                ft.Tab(text="Salary Management", content=ft.Container(content=salary_tab_content, padding=ft.Padding(top=15, left=0, right=0, bottom=0))),
                ft.Tab(text="Money Tracker", content=ft.Container(content=money_tab_content, padding=ft.Padding(top=15, left=0, right=0, bottom=0))),
            ],
        )

        # -------------------- BANNER AD --------------------
        banner_ad_slot = ft.Container(
            height=50,
            alignment=ft.Alignment(0, 0),
            content=ft.Text("Loading ad...", color="white", size=12) if page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS) else None
        )

        def load_banner_ad():
            if page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS):
                def on_ad_error(e):
                    banner_ad_slot.content = ft.Text(f"Ad failed to load: {e.data}", color="white", size=11)
                    page.update()

                def on_ad_load(e):
                    page.update()

                banner_ad_slot.content = fta.BannerAd(
                    unit_id=BANNER_AD_UNIT_ID.get(page.platform, BANNER_AD_UNIT_ID[ft.PagePlatform.ANDROID]),
                    width=320,
                    height=50,
                    on_load=on_ad_load,
                    on_error=on_ad_error,
                )
                page.update()

        content_wrapper = ft.Container(
            content=ft.Column(
                controls=[header_container, greeting_row, tabs, ft.Container(height=10), banner_ad_slot],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=5,
            ),
            width=420,
            alignment=ft.Alignment(0, -1),
        )

        main_content = ft.Column(
            controls=[content_wrapper],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

        view_container = ft.Stack(
            controls=[
                ft.Image(src="background.png", fit=ft.BoxFit.COVER, left=0, top=0, right=0, bottom=0),
                ft.Container(content=main_content, alignment=ft.Alignment(0, -1), padding=10, left=0, top=0, right=0, bottom=0),
            ],
            expand=True
        )

        page.controls.clear()
        page.add(view_container)
        load_banner_ad()
        page.update()

    # ==================================================================
    # STARTUP FLOW
    # ==================================================================
    try:
        terms_already_accepted = await page.shared_preferences.get("terms_accepted")
    except Exception:
        terms_already_accepted = False

    if not terms_already_accepted:
        show_terms_screen()
    else:
        await check_name()


async def main(page: ft.Page):
    try:
        await build_ui(page)
    except Exception as ex:
        import traceback
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

if __name__ == "__main__":
    ft.run(main)
