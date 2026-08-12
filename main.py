import flet as ft
import asyncio
import flet_ads as fta
import json
import datetime
from fpdf import FPDF

async def build_ui(page: ft.Page):
    page.title = "Naira Finance Hub"
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
            greeting_name.value = f"{new_name}!" if new_name else "Staff!"
            await page.shared_preferences.set("user_name", new_name)
            page.pop_dialog()
            page.update()

        name_field = ft.TextField(
            label="Your Name",
            value=greeting_name.value.rstrip("!") if greeting_name.value != "Staff!" else "",
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

    TUTORIAL_SLIDES = [
        {
            "icon": ft.Icons.HOME_ROUNDED,
            "icon_color": "#FF8C00",
            "title": "Housing Upfront",
            "text": "Calculate your housing upfront payment based on your basic salary, any increment, and your organization's rate — plus see your equivalent monthly housing allowance.",
        },
        {
            "icon": ft.Icons.WORK_ROUNDED,
            "icon_color": "#E53935",
            "title": "Salary Management",
            "text": "Get a full payslip breakdown — Gross Pay, Pension, NHF, and PAYE tax — using the current Nigeria Tax Act 2025 bands. Save calculations to compare over time.",
        },
        {
            "icon": ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED,
            "icon_color": "#1E88E5",
            "title": "Money Tracker",
            "text": "Log income and expenses by category, set monthly budgets, and view charts and trends — all stored only on your device. Tap 'More Options' for PDF export, backup & restore, and to replay this tutorial anytime.",
        },
    ]

    def show_tutorial_screen():
        slide_index = {"value": 0}
        slide_icon = ft.Icon(TUTORIAL_SLIDES[0]["icon"], size=70, color=TUTORIAL_SLIDES[0]["icon_color"])
        slide_title = ft.Text(TUTORIAL_SLIDES[0]["title"], size=22, weight=ft.FontWeight.BOLD, color="white", text_align=ft.TextAlign.CENTER)
        slide_text = ft.Text(TUTORIAL_SLIDES[0]["text"], size=14, color="white", text_align=ft.TextAlign.CENTER)
        dots_row = ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=8)
        next_btn_text = ft.Text("Next", weight=ft.FontWeight.BOLD, color="#4B0082")

        def build_dots():
            dots_row.controls = [
                ft.Container(
                    width=9, height=9, border_radius=5,
                    bgcolor="#FFD700" if i == slide_index["value"] else ft.Colors.with_opacity(0.3, ft.Colors.WHITE),
                )
                for i in range(len(TUTORIAL_SLIDES))
            ]

        def render_slide():
            s = TUTORIAL_SLIDES[slide_index["value"]]
            slide_icon.name = s["icon"]
            slide_icon.color = s["icon_color"]
            slide_title.value = s["title"]
            slide_text.value = s["text"]
            next_btn_text.value = "Get Started" if slide_index["value"] == len(TUTORIAL_SLIDES) - 1 else "Next"
            build_dots()
            page.update()

        async def finish_tutorial(e=None):
            await page.shared_preferences.set("tutorial_seen", True)
            await check_name()

        async def go_next(e):
            if slide_index["value"] < len(TUTORIAL_SLIDES) - 1:
                slide_index["value"] += 1
                render_slide()
            else:
                await finish_tutorial()

        async def skip_tutorial(e):
            await finish_tutorial()

        build_dots()

        page.controls.clear()
        page.bgcolor = "#4B0082"
        page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Container(height=20),
                        slide_icon,
                        ft.Container(height=10),
                        slide_title,
                        ft.Container(height=10),
                        ft.Container(content=slide_text, padding=ft.Padding(left=20, right=20, top=0, bottom=0)),
                        ft.Container(height=20),
                        dots_row,
                        ft.Container(height=30),
                        ft.ElevatedButton(
                            content=next_btn_text,
                            on_click=go_next,
                            style=ft.ButtonStyle(bgcolor="#FFD700"),
                            width=200,
                        ),
                        ft.TextButton(
                            content=ft.Text("Skip", color="white"),
                            on_click=skip_tutorial,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=4,
                ),
                padding=20,
                alignment=ft.Alignment(0, 0),
                expand=True,
            )
        )
        page.update()

    async def check_name():
        try:
            try:
                tutorial_seen = await page.shared_preferences.get("tutorial_seen")
            except Exception:
                tutorial_seen = False

            if not tutorial_seen:
                show_tutorial_screen()
                return

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
            content=ft.Text("Change Name", weight=ft.FontWeight.BOLD, size=11, color="#4B0082"),
            on_click=open_name_dialog,
            style=ft.ButtonStyle(bgcolor="#FFD700", padding=ft.Padding(left=8, right=8, top=4, bottom=4)),
        )

        wave_hand = ft.Container(
            content=ft.Text("🥰", size=20),
            rotate=0,
            animate_rotation=ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT),
        )

        async def animate_wave_loop():
            try:
                while True:
                    wave_hand.rotate = 0.35
                    page.update()
                    await asyncio.sleep(0.3)
                    wave_hand.rotate = -0.35
                    page.update()
                    await asyncio.sleep(0.3)
                    wave_hand.rotate = 0.35
                    page.update()
                    await asyncio.sleep(0.3)
                    wave_hand.rotate = 0
                    page.update()
                    await asyncio.sleep(1.5)
            except Exception:
                pass

        greeting_row = ft.Container(
            content=ft.Row(
                controls=[
                    change_btn,
                    ft.Container(
                        content=ft.Row(
                            controls=[ft.Text("Welcome back,", size=20, color="white"), greeting_name, wave_hand],
                            alignment=ft.MainAxisAlignment.CENTER,
                            spacing=10,
                            wrap=True,
                        ),
                        expand=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.START,
                spacing=10,
            ),
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border_radius=10,
            padding=ft.Padding(left=12, right=12, top=8, bottom=8),
        )

        logo_image = ft.Image(src="logo.png", width=90, height=90, fit=ft.BoxFit.CONTAIN)
        logo_container = ft.Container(
            content=logo_image,
            scale=1.0,
            rotate=0,
            animate_scale=ft.Animation(3300, ft.AnimationCurve.EASE_IN_OUT),
            animate_rotation=ft.Animation(18000, ft.AnimationCurve.LINEAR),
        )

        logo_backing_square = ft.Container(
            width=90,
            height=90,
            bgcolor="black",
            border_radius=10,
            rotate=0,
            animate_rotation=ft.Animation(18000, ft.AnimationCurve.LINEAR),
        )

        logo_stack = ft.Stack(
            controls=[logo_backing_square, logo_container],
            width=90,
            height=90,
        )

        logo_wrapper = ft.Container(
            content=logo_stack,
            offset=ft.Offset(0, 0),
            animate_offset=ft.Animation(80, ft.AnimationCurve.EASE_OUT),
        )

        async def animate_logo_pulse_loop():
            try:
                while True:
                    logo_container.scale = 1.08
                    page.update()
                    await asyncio.sleep(3.3)
                    logo_container.scale = 1.0
                    page.update()
                    await asyncio.sleep(3.3)
            except Exception:
                pass

        async def animate_logo_spin_loop():
            angle = 0.0
            square_angle = 0.0
            full_turn = 6.28318530718
            try:
                while True:
                    angle += full_turn
                    square_angle -= full_turn
                    logo_container.rotate = angle
                    logo_backing_square.rotate = square_angle
                    page.update()
                    await asyncio.sleep(18.0)
            except Exception:
                pass

        header_text = ft.Container(
            content=ft.Text(
                "Naira Finance Hub", size=22, weight=ft.FontWeight.BOLD, color="white",
                text_align=ft.TextAlign.CENTER
            ),
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border_radius=10,
            padding=ft.Padding(left=16, right=16, top=8, bottom=8),
        )

        header_container = ft.Container(
            content=ft.Column(
                controls=[logo_wrapper, header_text],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8
            ),
            padding=20,
            width=None,
        )

        try:
            saved_name = await page.shared_preferences.get("user_name")
            if saved_name:
                greeting_name.value = f"{saved_name}!"
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
        result_monthly_allowance = ft.Text(spans=[ft.TextSpan("Monthly Housing Allowance: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        result_basic = ft.Text(spans=[ft.TextSpan("New Basic: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        result_increment = ft.Text(spans=[ft.TextSpan("Increment Addition: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        result_total = ft.Text(spans=[ft.TextSpan("Annual Salary: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)

        async def on_calculate_click(e):
            try:
                salary = float(salary_input.value)
                increment_pct = float(increment_input.value)
                rate_pct = float(rate_input.value)
                increment_name = increment_label_input.value.strip() or "Increment"

                increment_amount = salary * (increment_pct / 100.0)
                new_basic = salary + increment_amount
                annual_salary = new_basic * 12.0
                upfront_amount = annual_salary * (rate_pct / 100.0)
                monthly_allowance = upfront_amount / 12.0

                result_upfront.spans[1].text = f"₦{upfront_amount:,.2f}"
                result_monthly_allowance.spans[1].text = f"₦{monthly_allowance:,.2f}"
                result_basic.spans[1].text = f"₦{new_basic:,.2f}"
                result_increment.spans[0].text = f"{increment_name} Addition: "
                result_increment.spans[1].text = f"₦{increment_amount:,.2f}"
                result_total.spans[1].text = f"₦{annual_salary:,.2f}"

                housing_results.scale = 0.92
                page.update()
                await asyncio.sleep(0.08)
                housing_results.scale = 1
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
                    field_with_caption("Increment Name (e.g. NJIC)", increment_label_input),
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
            content=ft.Column([result_upfront, result_monthly_allowance, ft.Divider(height=1, color="#4B0082"), result_basic, result_increment, result_total], spacing=8, tight=True),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border=ft.Border(ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700")),
            shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK)),
            scale=1,
            animate_scale=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
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

        async def sm_on_calculate_click(e):
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
                sm_results.scale = 0.92
                page.update()
                await asyncio.sleep(0.08)
                sm_results.scale = 1
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
        CATEGORY_OPTIONS = ["Food", "Transport", "Housing", "Utilities", "Health", "Entertainment", "Salary", "Business", "Miscellaneous", "Fee", "Other"]
        CATEGORY_ICONS = {
            "Food": ft.Icons.RESTAURANT_ROUNDED,
            "Transport": ft.Icons.DIRECTIONS_CAR_ROUNDED,
            "Housing": ft.Icons.HOME_ROUNDED,
            "Utilities": ft.Icons.BOLT_ROUNDED,
            "Health": ft.Icons.LOCAL_HOSPITAL_ROUNDED,
            "Entertainment": ft.Icons.MOVIE_ROUNDED,
            "Salary": ft.Icons.PAYMENTS_ROUNDED,
            "Business": ft.Icons.BUSINESS_CENTER_ROUNDED,
            "Miscellaneous": ft.Icons.CATEGORY_ROUNDED,
            "Fee": ft.Icons.RECEIPT_LONG_ROUNDED,
            "Other": ft.Icons.LABEL_ROUNDED,
        }

        def category_icon(cat):
            return CATEGORY_ICONS.get(cat, ft.Icons.LABEL_ROUNDED)


        def category_dropdown_options():
            return [
                ft.dropdown.Option(key=c, text=c)
                for c in CATEGORY_OPTIONS
            ]

        async def load_transactions():
            try:
                raw = await page.shared_preferences.get("money_transactions")
                return json.loads(raw) if raw else []
            except Exception:
                return []

        async def save_transactions(transactions):
            await page.shared_preferences.set("money_transactions", json.dumps(transactions))

        # -------------------- CATEGORY BUDGETS --------------------
        async def load_budgets():
            try:
                raw = await page.shared_preferences.get("category_budgets")
                return json.loads(raw) if raw else {}
            except Exception:
                return {}

        async def save_budgets(budgets):
            await page.shared_preferences.set("category_budgets", json.dumps(budgets))

        def open_budget_dialog():
            budget_category_picker, budget_category_state = build_category_picker("Food")
            budget_amount_input = ft.TextField(
                keyboard_type=ft.KeyboardType.NUMBER,
                bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
                text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                hint_text="e.g. 50000",
            )
            budget_error_text = ft.Text("", color="red", size=12)

            async def save_budget(e):
                try:
                    amount = float(budget_amount_input.value)
                except (ValueError, TypeError):
                    budget_error_text.value = "Enter a valid amount."
                    page.update()
                    return
                budgets = await load_budgets()
                budgets[budget_category_state["value"]] = amount
                await save_budgets(budgets)
                page.pop_dialog()
                await refresh_money_ui()

            async def remove_budget(e):
                budgets = await load_budgets()
                budgets.pop(budget_category_state["value"], None)
                await save_budgets(budgets)
                page.pop_dialog()
                await refresh_money_ui()

            dlg = ft.AlertDialog(
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text("Set Monthly Budget", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("Set a monthly spending limit for a category. You'll get a visual warning as you approach or exceed it.", color=DARK_TEXT, size=12),
                            field_with_caption("Category", budget_category_picker),
                            field_with_caption("Monthly Limit (₦)", budget_amount_input),
                            budget_error_text,
                        ],
                        tight=True, spacing=15, scroll=ft.ScrollMode.AUTO,
                    ),
                    width=300, height=320,
                ),
                actions=[
                    ft.TextButton("Remove Budget", on_click=remove_budget, style=ft.ButtonStyle(color="#C62828")),
                    ft.TextButton("Save", on_click=save_budget, style=ft.ButtonStyle(color=PURPLE_TEXT)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dlg)

        def show_undo_snackbar(deleted_entry):
            async def handle_undo(e):
                full = await load_transactions()
                full.insert(0, deleted_entry)
                await save_transactions(full)
                await refresh_money_ui()

            page.show_dialog(
                ft.SnackBar(
                    ft.Text("Transaction deleted", color="white"),
                    action="Undo",
                    on_action=handle_undo,
                    duration=ft.Duration(seconds=5),
                    bgcolor=PURPLE_TEXT,
                )
            )

        # -------------------- PDF LOG BOOK EXPORT --------------------
        def build_transactions_pdf_bytes(title, txn_list):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(0, 10, "Naira Finance Hub", ln=True, align="C")
            pdf.set_font("Helvetica", "", 12)
            pdf.cell(0, 8, title, ln=True, align="C")
            pdf.ln(4)

            total_income = sum(t["amount"] for t in txn_list if t["type"] == "income")
            total_expense = sum(t["amount"] for t in txn_list if t["type"] == "expense")
            net = total_income - total_expense

            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, f"Total Income: NGN {total_income:,.2f}", ln=True)
            pdf.cell(0, 7, f"Total Expense: NGN {total_expense:,.2f}", ln=True)
            pdf.cell(0, 7, f"Net: NGN {net:,.2f}", ln=True)
            pdf.ln(6)

            pdf.set_font("Helvetica", "B", 10)
            pdf.set_fill_color(230, 230, 230)
            pdf.cell(25, 8, "Date", border=1, fill=True)
            pdf.cell(20, 8, "Type", border=1, fill=True)
            pdf.cell(35, 8, "Category", border=1, fill=True)
            pdf.cell(65, 8, "Note", border=1, fill=True)
            pdf.cell(35, 8, "Amount", border=1, fill=True, ln=True)

            pdf.set_font("Helvetica", "", 9)
            sorted_txns = sorted(txn_list, key=lambda t: t.get("date", ""))
            for t in sorted_txns:
                sign = "+" if t["type"] == "income" else "-"
                note = (t.get("note", "") or "-")[:35]
                pdf.cell(25, 7, t.get("date", ""), border=1)
                pdf.cell(20, 7, t["type"].capitalize(), border=1)
                pdf.cell(35, 7, t.get("category", "Other")[:20], border=1)
                pdf.cell(65, 7, note, border=1)
                pdf.cell(35, 7, f"{sign}NGN {t['amount']:,.2f}", border=1, ln=True)

            return bytes(pdf.output())

        pdf_file_picker = ft.FilePicker()
        page.services.append(pdf_file_picker)

        async def export_month_pdf(e):
            transactions = await load_transactions()
            view_year = current_view_date["year"]
            view_month = current_view_date["month"]
            month_txns = []
            for t in transactions:
                try:
                    d = datetime.date.fromisoformat(t["date"])
                except Exception:
                    continue
                if d.year == view_year and d.month == view_month:
                    month_txns.append(t)

            month_name = datetime.date(view_year, view_month, 1).strftime("%B %Y")
            pdf_bytes = build_transactions_pdf_bytes(f"Monthly Log - {month_name}", month_txns)
            file_path = await pdf_file_picker.save_file(
                dialog_title="Save Monthly Log",
                file_name=f"NairaFinanceHub_{month_name.replace(' ', '_')}.pdf",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["pdf"],
                src_bytes=pdf_bytes,
            )
            mt_status_text.value = "Monthly log saved!" if file_path else "Save cancelled."
            page.update()

        async def export_year_pdf(e):
            transactions = await load_transactions()
            view_year = current_view_date["year"]
            year_txns = []
            for t in transactions:
                try:
                    d = datetime.date.fromisoformat(t["date"])
                except Exception:
                    continue
                if d.year == view_year:
                    year_txns.append(t)

            pdf_bytes = build_transactions_pdf_bytes(f"Annual Log - {view_year}", year_txns)
            file_path = await pdf_file_picker.save_file(
                dialog_title="Save Annual Log",
                file_name=f"NairaFinanceHub_{view_year}_Annual.pdf",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["pdf"],
                src_bytes=pdf_bytes,
            )
            mt_status_text.value = "Annual log saved!" if file_path else "Save cancelled."
            page.update()

        # -------------------- BACKUP & RESTORE --------------------
        async def backup_data(e):
            try:
                raw = await page.shared_preferences.get("money_transactions")
                money_transactions = json.loads(raw) if raw else []
            except Exception:
                money_transactions = []

            try:
                saved_username = await page.shared_preferences.get("user_name")
            except Exception:
                saved_username = ""

            backup_obj = {
                "app": "Naira Finance Hub",
                "backup_version": 1,
                "created": datetime.datetime.now().isoformat(),
                "money_transactions": money_transactions,
                "user_name": saved_username or "",
            }
            backup_bytes = json.dumps(backup_obj, indent=2).encode("utf-8")

            file_path = await pdf_file_picker.save_file(
                dialog_title="Save Backup File",
                file_name=f"NairaFinanceHub_Backup_{datetime.date.today().isoformat()}.json",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["json"],
                src_bytes=backup_bytes,
            )
            page.show_dialog(ft.SnackBar(ft.Text("Backup saved! Keep this file somewhere safe." if file_path else "Backup cancelled.", color="white"), bgcolor=PURPLE_TEXT, duration=ft.Duration(seconds=3)))
            page.update()

        async def restore_data(e):
            result = await pdf_file_picker.pick_files(
                dialog_title="Select Backup File to Restore",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["json"],
                allow_multiple=False,
                with_data=True,
            )
            files = getattr(result, "files", result)
            if not files:
                page.show_dialog(ft.SnackBar(ft.Text("Restore cancelled.", color="white"), bgcolor=PURPLE_TEXT, duration=ft.Duration(seconds=3)))
                page.update()
                return

            picked = files[0]
            if not getattr(picked, "bytes", None):
                page.show_dialog(ft.SnackBar(ft.Text("Could not read that file. Please try again.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3)))
                page.update()
                return

            try:
                backup_obj = json.loads(picked.bytes.decode("utf-8"))
                restored_transactions = backup_obj.get("money_transactions", [])
                await page.shared_preferences.set("money_transactions", json.dumps(restored_transactions))
                if backup_obj.get("user_name"):
                    await page.shared_preferences.set("user_name", backup_obj["user_name"])
                page.show_dialog(ft.SnackBar(ft.Text("Backup restored! Your transactions are back.", color="white"), bgcolor="#2E8B57", duration=ft.Duration(seconds=3)))
                await refresh_money_ui()
                page.update()
            except Exception:
                page.show_dialog(ft.SnackBar(ft.Text("That doesn't look like a valid backup file.", color="white"), bgcolor="#C62828", duration=ft.Duration(seconds=3)))
                page.update()

        def show_backup_help(e):
            dlg = ft.AlertDialog(
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text("Backup & Restore — How It Works", color="#C62828", weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(
                                "This app has no login or account — everything lives only on this phone. Backup & Restore lets you keep a safe copy so nothing is lost.",
                                color=DARK_TEXT, size=13
                            ),
                            ft.Text("📤 Backup", weight=ft.FontWeight.BOLD, color="#C62828", size=13),
                            ft.Text(
                                "Tap 'Backup Data' to save all your transactions into one file. Choose where to save it — Downloads, Google Drive, or email it to yourself.",
                                color=DARK_TEXT, size=12
                            ),
                            ft.Text("📥 Restore", weight=ft.FontWeight.BOLD, color="#C62828", size=13),
                            ft.Text(
                                "On a new phone, or after reinstalling the app, tap 'Restore Data' and select your saved backup file. Your transactions will load right back in.",
                                color=DARK_TEXT, size=12
                            ),
                            ft.Text(
                                "⚠ Back up regularly, and keep the file somewhere safe. If the file is lost, the data inside it cannot be recovered.",
                                color="#C62828", size=12, weight=ft.FontWeight.BOLD
                            ),
                        ],
                        scroll=ft.ScrollMode.AUTO, spacing=10, tight=True,
                    ),
                    width=300, height=380,
                ),
                actions=[ft.TextButton("Got it", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT))],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dlg)

        today = datetime.date.today()
        current_view_date = {"year": today.year, "month": today.month}

        def build_type_toggle(initial_value):
            state = {"value": initial_value}
            income_btn = ft.ElevatedButton(
                content=ft.Text("Income", weight=ft.FontWeight.BOLD, size=13, color=PURPLE_TEXT if initial_value == "income" else "white"),
                style=ft.ButtonStyle(bgcolor="#FFD700" if initial_value == "income" else ft.Colors.with_opacity(0.3, ft.Colors.WHITE)),
            )
            expense_btn = ft.ElevatedButton(
                content=ft.Text("Expense", weight=ft.FontWeight.BOLD, size=13, color=PURPLE_TEXT if initial_value == "expense" else "white"),
                style=ft.ButtonStyle(bgcolor="#FFD700" if initial_value == "expense" else ft.Colors.with_opacity(0.3, ft.Colors.WHITE)),
            )

            def select(val):
                def handler(e):
                    state["value"] = val
                    income_btn.style = ft.ButtonStyle(bgcolor="#FFD700" if val == "income" else ft.Colors.with_opacity(0.3, ft.Colors.WHITE))
                    income_btn.content.color = PURPLE_TEXT if val == "income" else "white"
                    expense_btn.style = ft.ButtonStyle(bgcolor="#FFD700" if val == "expense" else ft.Colors.with_opacity(0.3, ft.Colors.WHITE))
                    expense_btn.content.color = PURPLE_TEXT if val == "expense" else "white"
                    page.update()
                return handler

            income_btn.on_click = select("income")
            expense_btn.on_click = select("expense")
            row = ft.Row([income_btn, expense_btn], spacing=8)
            return row, state

        def build_category_picker(initial_value):
            state = {"value": initial_value}
            label_text = ft.Text(initial_value, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=14)
            label_icon = ft.Icon(category_icon(initial_value), color=PURPLE_TEXT, size=18)

            def open_picker(e):
                def pick(cat):
                    def handler(e):
                        state["value"] = cat
                        label_text.value = cat
                        label_icon.name = category_icon(cat)
                        page.pop_dialog()
                        page.update()
                    return handler

                rows = [
                    ft.TextButton(
                        content=ft.Container(
                            content=ft.Row(
                                [ft.Icon(category_icon(c), color=PURPLE_TEXT, size=18), ft.Text(c, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD)],
                                spacing=10,
                            ),
                            width=220,
                        ),
                        on_click=pick(c),
                    )
                    for c in CATEGORY_OPTIONS
                ]
                dlg = ft.AlertDialog(
                    modal=True,
                    bgcolor="#FFFFFF",
                    title=ft.Text("Select Category", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                    content=ft.Container(content=ft.ListView(controls=rows, spacing=2), width=260, height=350),
                    actions=[ft.TextButton("Cancel", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT))],
                    actions_alignment=ft.MainAxisAlignment.END,
                )
                page.show_dialog(dlg)

            picker_btn = ft.ElevatedButton(
                content=ft.Row(
                    [ft.Row([label_icon, label_text], spacing=8), ft.Icon(ft.Icons.ARROW_DROP_DOWN, color=PURPLE_TEXT)],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                on_click=open_picker,
                style=ft.ButtonStyle(bgcolor="#FFFFFF", side=ft.BorderSide(1, PURPLE_TEXT)),
                width=280,
            )
            return picker_btn, state

        mt_type_row, mt_type_state = build_type_toggle("income")
        mt_category_picker, mt_category_state = build_category_picker("Other")
        mt_amount_input = ft.TextField(keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD))
        mt_note_input = ft.TextField(bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT, text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD))
        mt_status_text = ft.Text("", color="white", size=12, text_align=ft.TextAlign.CENTER)

        mt_selected_date = {"value": None}
        mt_date_button_text = ft.Text("Transaction Date (Optional)", color="#4B0082", size=12, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)

        def mt_on_date_picked(e):
            picked = e.control.value
            if picked:
                picked_date = picked.date() if hasattr(picked, "date") else picked
                if picked_date > datetime.date.today():
                    mt_status_text.value = "You can't select a future date. Please pick today or an earlier date."
                    page.update()
                    return
                mt_selected_date["value"] = picked_date
                mt_date_button_text.value = picked_date.strftime("%d %b %Y")
                mt_status_text.value = ""
                page.update()

        mt_date_picker = ft.DatePicker(
            first_date=datetime.datetime(2020, 1, 1),
            last_date=datetime.datetime.now(),
            current_date=datetime.datetime.now(),
            on_change=mt_on_date_picked,
        )

        mt_date_button = ft.ElevatedButton(
            content=ft.Container(content=mt_date_button_text, width=190),
            on_click=lambda e: page.show_dialog(mt_date_picker),
            style=ft.ButtonStyle(bgcolor="#FFD700"),
        )

        mt_month_label = ft.Text("", size=16, weight=ft.FontWeight.BOLD, color="white")

        mt_summary_income = ft.Text(spans=[ft.TextSpan("Income: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        mt_summary_expense = ft.Text(spans=[ft.TextSpan("Expense: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        mt_summary_net = ft.Text(spans=[ft.TextSpan("Net: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=18)

        mt_annual_label = ft.Text("", size=15, weight=ft.FontWeight.BOLD, color="white", text_align=ft.TextAlign.CENTER)
        mt_annual_income = ft.Text(spans=[ft.TextSpan("Total Income: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        mt_annual_expense = ft.Text(spans=[ft.TextSpan("Total Expense: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
        mt_annual_net = ft.Text(spans=[ft.TextSpan("Annual Net: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=18)
        mt_annual_category_list_view = ft.Column([], spacing=6)

        mt_chart_container = ft.Container(padding=10, alignment=ft.Alignment(0, 0))
        mt_category_list_view = ft.Column([], spacing=6)
        mt_transactions_list_view = ft.ListView(controls=[], spacing=8, height=260)
        mt_search_query = {"value": ""}

        async def on_search_change(e):
            mt_search_query["value"] = (mt_search_input.value or "").strip().lower()
            await refresh_money_ui()

        mt_search_input = ft.TextField(
            hint_text="Search by note or category...",
            bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
            text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            prefix_icon=ft.Icons.SEARCH_ROUNDED,
            on_change=on_search_change,
        )


        def open_edit_dialog(actual_idx, entry):
            edit_type_row, edit_type_state = build_type_toggle(entry.get("type", "expense"))
            edit_category_picker, edit_category_state = build_category_picker(entry.get("category", "Other"))
            edit_amount_input = ft.TextField(
                value=str(entry.get("amount", "")), keyboard_type=ft.KeyboardType.NUMBER,
                bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
                text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            )
            edit_note_input = ft.TextField(
                value=entry.get("note", ""),
                bgcolor="#FFFFFF", border_color=PURPLE_TEXT, color=PURPLE_TEXT,
                text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            )
            edit_error_text = ft.Text("", color="red", size=12)

            try:
                existing_date = datetime.date.fromisoformat(entry.get("date", ""))
            except Exception:
                existing_date = datetime.date.today()
            edit_selected_date = {"value": existing_date}
            edit_date_button_text = ft.Text(existing_date.strftime("%d %b %Y"), color=PURPLE_TEXT, size=13, weight=ft.FontWeight.BOLD)

            def edit_on_date_picked(e):
                picked = e.control.value
                if picked:
                    picked_date = picked.date() if hasattr(picked, "date") else picked
                    if picked_date > datetime.date.today():
                        edit_error_text.value = "You can't select a future date. Please pick today or an earlier date."
                        page.update()
                        return
                    edit_selected_date["value"] = picked_date
                    edit_date_button_text.value = picked_date.strftime("%d %b %Y")
                    edit_error_text.value = ""
                    page.update()

            edit_date_picker = ft.DatePicker(
                first_date=datetime.datetime(2020, 1, 1),
                last_date=datetime.datetime.now(),
                current_date=datetime.datetime(existing_date.year, existing_date.month, existing_date.day),
                on_change=edit_on_date_picked,
            )
            edit_date_button = ft.ElevatedButton(
                content=ft.Container(content=edit_date_button_text, width=200),
                on_click=lambda e: page.show_dialog(edit_date_picker),
                style=ft.ButtonStyle(bgcolor="#FFD700"),
            )

            async def save_edit(e):
                try:
                    new_amount = float(edit_amount_input.value)
                except (ValueError, TypeError):
                    edit_error_text.value = "Enter a valid amount."
                    page.update()
                    return
                full = await load_transactions()
                if 0 <= actual_idx < len(full):
                    full[actual_idx]["type"] = edit_type_state["value"]
                    full[actual_idx]["category"] = edit_category_state["value"]
                    full[actual_idx]["amount"] = new_amount
                    full[actual_idx]["note"] = (edit_note_input.value or "").strip()
                    full[actual_idx]["date"] = edit_selected_date["value"].isoformat()
                    await save_transactions(full)
                page.pop_dialog()
                await refresh_money_ui()

            async def delete_from_edit(e):
                full = await load_transactions()
                deleted_entry = None
                if 0 <= actual_idx < len(full):
                    deleted_entry = full[actual_idx]
                    del full[actual_idx]
                await save_transactions(full)
                page.pop_dialog()
                await refresh_money_ui()
                if deleted_entry:
                    show_undo_snackbar(deleted_entry)

            edit_dialog = ft.AlertDialog(
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text("Edit Transaction", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            field_with_caption("Type", edit_type_row),
                            field_with_caption("Category", edit_category_picker),
                            field_with_caption("Amount (₦)", edit_amount_input),
                            field_with_caption("Note", edit_note_input),
                            field_with_caption("Date", edit_date_button),
                            edit_error_text,
                        ],
                        tight=True, spacing=15, scroll=ft.ScrollMode.AUTO,
                    ),
                    width=300, height=400,
                ),
                actions=[
                    ft.TextButton("Delete", on_click=delete_from_edit, style=ft.ButtonStyle(color="#C62828")),
                    ft.TextButton("Save", on_click=save_edit, style=ft.ButtonStyle(color=PURPLE_TEXT)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(edit_dialog)

        async def refresh_money_ui():
            mt_month_label.value = datetime.date(current_view_date["year"], current_view_date["month"], 1).strftime("%B %Y")

            bounce_icon_containers = []

            def bouncy_icon(cat, size=16, color="white"):
                c = ft.Container(
                    content=ft.Icon(category_icon(cat), size=size, color=color),
                    scale=0,
                    animate_scale=ft.Animation(600, ft.AnimationCurve.BOUNCE_OUT),
                )
                bounce_icon_containers.append(c)
                return c

            transactions = await load_transactions()
            view_year = current_view_date["year"]
            view_month = current_view_date["month"]

            month_income = 0.0
            month_expense = 0.0
            category_totals = {}
            filtered = []

            for idx, t in enumerate(transactions):
                try:
                    d = datetime.date.fromisoformat(t["date"])
                except Exception:
                    continue
                if d.year == view_year and d.month == view_month:
                    filtered.append((idx, t))
                    cat = t.get("category", "Other")
                    entry = category_totals.setdefault(cat, {"income": 0.0, "expense": 0.0})
                    if t["type"] == "income":
                        month_income += t["amount"]
                        entry["income"] += t["amount"]
                    else:
                        month_expense += t["amount"]
                        entry["expense"] += t["amount"]

            net = month_income - month_expense
            mt_summary_income.spans[1].text = f"₦{month_income:,.2f}"
            mt_summary_expense.spans[1].text = f"₦{month_expense:,.2f}"
            mt_summary_net.spans[1].text = f"₦{net:,.2f}"

            # Annual accumulation across every month of the currently-viewed year
            annual_income = 0.0
            annual_expense = 0.0
            annual_category_totals = {}
            for t in transactions:
                try:
                    d = datetime.date.fromisoformat(t["date"])
                except Exception:
                    continue
                if d.year == view_year:
                    cat = t.get("category", "Other")
                    cat_entry = annual_category_totals.setdefault(cat, {"income": 0.0, "expense": 0.0})
                    if t["type"] == "income":
                        annual_income += t["amount"]
                        cat_entry["income"] += t["amount"]
                    else:
                        annual_expense += t["amount"]
                        cat_entry["expense"] += t["amount"]
            annual_net = annual_income - annual_expense

            mt_annual_label.value = f"Annual Summary ({view_year})"
            mt_annual_income.spans[1].text = f"₦{annual_income:,.2f}"
            mt_annual_expense.spans[1].text = f"₦{annual_expense:,.2f}"
            mt_annual_net.spans[1].text = f"₦{annual_net:,.2f}"

            if annual_category_totals:
                annual_entries = []
                for cat, v in annual_category_totals.items():
                    if v["income"] > 0:
                        annual_entries.append((cat, "income", v["income"]))
                    if v["expense"] > 0:
                        annual_entries.append((cat, "expense", v["expense"]))
                sorted_annual_cats = sorted(annual_entries, key=lambda x: x[2], reverse=True)
                mt_annual_category_list_view.controls = [
                    ft.Row(
                        [
                            ft.Row([bouncy_icon(cat), ft.Text(f"{cat} ({'Income' if kind == 'income' else 'Expense'})", color="white", size=13)], spacing=6),
                            ft.Text(f"{'+' if kind == 'income' else '-'}₦{amt:,.2f}", color="#2E8B57" if kind == "income" else "#C62828", size=13, weight=ft.FontWeight.BOLD),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )
                    for cat, kind, amt in sorted_annual_cats
                ]
            else:
                mt_annual_category_list_view.controls = [ft.Text("No transactions this year yet.", color="white", size=12)]

            # Build a per-category bar so the user can see where money actually goes.
            # Income and expense on the SAME category are shown as separate bars,
            # not netted together, so both flows stay visible.
            category_entries = []
            for cat, v in category_totals.items():
                if v["income"] > 0:
                    category_entries.append((cat, "income", v["income"]))
                if v["expense"] > 0:
                    category_entries.append((cat, "expense", v["expense"]))
            sorted_categories = sorted(category_entries, key=lambda x: x[2], reverse=True)[:10]

            if sorted_categories:
                max_bar_height = 150
                max_abs = max((amt for _, _, amt in sorted_categories), default=1.0) or 1.0

                category_units = []
                for cat, kind, amt in sorted_categories:
                    bar_height = max(10, (amt / max_abs) * max_bar_height)
                    bar_color = "#2E8B57" if kind == "income" else "#C62828"
                    tag = "In" if kind == "income" else "Out"
                    category_units.append(
                        ft.Column(
                            [
                                ft.Container(
                                    content=ft.Container(height=bar_height, width=44, bgcolor=bar_color, border_radius=6),
                                    height=max_bar_height,
                                    alignment=ft.Alignment(0, 1),
                                ),
                                ft.Text(f"₦{amt:,.0f}", size=10, color="white"),
                                ft.Text(f"{cat} ({tag})", size=10, color="white", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=4,
                            width=72,
                        )
                    )

                mt_chart_container.content = ft.Row(
                    category_units,
                    spacing=10,
                    scroll=ft.ScrollMode.AUTO,
                )
            else:
                mt_chart_container.content = ft.Text("No transactions this month yet.", color="white", size=13, text_align=ft.TextAlign.CENTER)

            if category_totals:
                list_entries = []
                for cat, v in category_totals.items():
                    if v["income"] > 0:
                        list_entries.append((cat, "income", v["income"]))
                    if v["expense"] > 0:
                        list_entries.append((cat, "expense", v["expense"]))
                sorted_cats_full = sorted(list_entries, key=lambda x: x[2], reverse=True)
                category_rows = [
                    ft.Row(
                        [
                            ft.Row([bouncy_icon(cat), ft.Text(f"{cat} ({'Income' if kind == 'income' else 'Expense'})", color="white", size=13)], spacing=6),
                            ft.Text(f"{'+' if kind == 'income' else '-'}₦{amt:,.2f}", color="#2E8B57" if kind == "income" else "#C62828", size=13, weight=ft.FontWeight.BOLD),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )
                    for cat, kind, amt in sorted_cats_full
                ]

                budgets = await load_budgets()
                if budgets:
                    budget_rows = []
                    for cat, limit in budgets.items():
                        spent = category_totals.get(cat, {}).get("expense", 0.0)
                        pct = (spent / limit * 100.0) if limit > 0 else 0.0
                        if pct >= 100:
                            status_color = "#C62828"
                            status_text = f"Over budget! ₦{spent:,.0f} of ₦{limit:,.0f}"
                        elif pct >= 80:
                            status_color = "#FF8C00"
                            status_text = f"{pct:.0f}% used — ₦{spent:,.0f} of ₦{limit:,.0f}"
                        else:
                            status_color = "#2E8B57"
                            status_text = f"{pct:.0f}% used — ₦{spent:,.0f} of ₦{limit:,.0f}"
                        budget_rows.append(
                            ft.Column(
                                [
                                    ft.Row([bouncy_icon(cat), ft.Text(f"{cat} Budget", color="white", size=12, weight=ft.FontWeight.BOLD)], spacing=6),
                                    ft.Container(
                                        content=ft.Container(
                                            width=min(pct, 100) * 2.2,
                                            height=8,
                                            bgcolor=status_color,
                                            border_radius=4,
                                        ),
                                        width=220, height=8, bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.WHITE), border_radius=4,
                                    ),
                                    ft.Text(status_text, color=status_color, size=11, weight=ft.FontWeight.BOLD),
                                ],
                                spacing=4,
                            )
                        )
                    category_rows.append(ft.Divider(height=1, color="#4B0082"))
                    category_rows.append(ft.Text("Budgets", color="white", weight=ft.FontWeight.BOLD, size=13))
                    category_rows.extend(budget_rows)

                mt_category_list_view.controls = category_rows
            else:
                mt_category_list_view.controls = [ft.Text("No transactions this month yet.", color="white", size=12)]

            def make_delete(actual_idx):
                async def _delete(e):
                    full = await load_transactions()
                    deleted_entry = None
                    if 0 <= actual_idx < len(full):
                        deleted_entry = full[actual_idx]
                        del full[actual_idx]
                    await save_transactions(full)
                    await refresh_money_ui()
                    page.update()
                    if deleted_entry:
                        show_undo_snackbar(deleted_entry)
                return _delete

            def make_row_click(actual_idx, entry):
                def _click(e):
                    open_edit_dialog(actual_idx, entry)
                return _click

            search_q = mt_search_query["value"]
            if search_q:
                display_filtered = [
                    (idx, t) for idx, t in filtered
                    if search_q in (t.get("note", "") or "").lower() or search_q in (t.get("category", "") or "").lower()
                ]
            else:
                display_filtered = filtered

            rows = []
            for actual_idx, t in display_filtered[:30]:
                color = "#2E8B57" if t["type"] == "income" else "#C62828"
                sign = "+" if t["type"] == "income" else "-"
                rows.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                bouncy_icon(t.get("category", "Other"), size=20),
                                ft.Column(
                                    [
                                        ft.Text(t.get("note", "") or t["type"].capitalize(), weight=ft.FontWeight.BOLD, color="white", size=13),
                                        ft.Text(f"{t.get('category', 'Other')} • {t.get('date', '')}", size=10, color="#666666"),
                                    ],
                                    spacing=0, expand=True,
                                ),
                                ft.Text(f"{sign}₦{t['amount']:,.2f}", color=color, weight=ft.FontWeight.BOLD),
                                ft.IconButton(icon=ft.Icons.CLOSE, icon_color="#C62828", icon_size=16, on_click=make_delete(actual_idx)),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        on_click=make_row_click(actual_idx, t),
                        padding=ft.Padding(top=6, bottom=6, left=6, right=6),
                        border_radius=6,
                        ink=True,
                    )
                )
            if rows:
                mt_transactions_list_view.controls = rows
            elif search_q:
                mt_transactions_list_view.controls = [ft.Text(f"No results for '{mt_search_input.value}'.", color=DARK_TEXT, size=12)]
            else:
                mt_transactions_list_view.controls = [ft.Text("No transactions this month. Tap a row to edit.", color=DARK_TEXT, size=12)]
            page.update()
            await asyncio.sleep(0.25)
            for c in bounce_icon_containers:
                c.scale = 1
            page.update()

        async def go_prev_month(e):
            m = current_view_date["month"] - 1
            y = current_view_date["year"]
            if m < 1:
                m, y = 12, y - 1
            current_view_date["month"], current_view_date["year"] = m, y
            await refresh_money_ui()

        async def go_next_month(e):
            m = current_view_date["month"] + 1
            y = current_view_date["year"]
            if m > 12:
                m, y = 1, y + 1
            real_today = datetime.date.today()
            if (y, m) > (real_today.year, real_today.month):
                return
            current_view_date["month"], current_view_date["year"] = m, y
            await refresh_money_ui()

        mt_month_nav = ft.Container(
            content=ft.Row(
                [
                    ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, icon_color="white", on_click=go_prev_month),
                    mt_month_label,
                    ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, icon_color="white", on_click=go_next_month),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border_radius=10,
            padding=ft.Padding(left=10, right=10, top=4, bottom=4),
        )

        async def mt_on_add_click(e):
            try:
                amount = float(mt_amount_input.value)
            except (ValueError, TypeError):
                mt_status_text.value = "Please enter a valid amount."
                page.update()
                return
            chosen_date = mt_selected_date["value"] or datetime.date.today()
            entry = {
                "type": mt_type_state["value"] or "income",
                "category": mt_category_state["value"] or "Other",
                "amount": amount,
                "note": (mt_note_input.value or "").strip(),
                "date": chosen_date.isoformat(),
            }
            transactions = await load_transactions()
            transactions.insert(0, entry)
            transactions = transactions[:10000]
            await save_transactions(transactions)
            mt_amount_input.value = ""
            mt_note_input.value = ""
            mt_selected_date["value"] = None
            mt_date_button_text.value = "Transaction Date (Optional)"
            mt_status_text.value = "Transaction added."
            current_view_date["year"] = today.year
            current_view_date["month"] = today.month
            await refresh_money_ui()
            page.update()

        mt_add_btn = ft.ElevatedButton("Add Transaction", on_click=mt_on_add_click, style=ft.ButtonStyle(bgcolor="#FFD700", color="#4B0082", text_style=ft.TextStyle(weight=ft.FontWeight.BOLD)))

        mt_form = ft.Container(
            content=ft.Column(
                controls=[
                    field_with_caption("Type", mt_type_row),
                    field_with_caption("Category", mt_category_picker),
                    field_with_caption("Amount (₦)", mt_amount_input),
                    field_with_caption("Note (optional)", mt_note_input),
                    field_with_caption("Date", mt_date_button),
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
            shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK)),
            scale=1,
            animate_scale=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )

        mt_annual_container = ft.Container(
            content=ft.Column(
                [
                    mt_annual_label, ft.Divider(height=1, color="#4B0082"),
                    mt_annual_income, mt_annual_expense, mt_annual_net,
                    ft.Divider(height=1, color="#4B0082"),
                    ft.Text("By Category (Full Year)", color="white", weight=ft.FontWeight.BOLD, size=13),
                    mt_annual_category_list_view,
                ],
                spacing=8, tight=True,
            ),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            border=ft.Border(ft.BorderSide(2, "#1E88E5"), ft.BorderSide(2, "#1E88E5"), ft.BorderSide(2, "#1E88E5"), ft.BorderSide(2, "#1E88E5")),
            shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK)),
        )

        def open_more_options_menu(e):
            def make_option_row(icon, label, color, action):
                async def run_after_close(e):
                    page.pop_dialog()
                    await action(e)
                return ft.TextButton(
                    content=ft.Container(
                        content=ft.Row(
                            [ft.Icon(icon, color=color, size=20), ft.Text(label, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=14)],
                            spacing=12,
                        ),
                        width=240,
                    ),
                    on_click=run_after_close,
                )

            def make_sync_option_row(icon, label, color, action):
                def handler(e):
                    page.pop_dialog()
                    action(e)
                return ft.TextButton(
                    content=ft.Container(
                        content=ft.Row(
                            [ft.Icon(icon, color=color, size=20), ft.Text(label, color=PURPLE_TEXT, weight=ft.FontWeight.BOLD, size=14)],
                            spacing=12,
                        ),
                        width=240,
                    ),
                    on_click=handler,
                )

            rows = [
                make_option_row(ft.Icons.PICTURE_AS_PDF_ROUNDED, "Export Month (PDF)", "#C62828", export_month_pdf),
                make_option_row(ft.Icons.PICTURE_AS_PDF_ROUNDED, "Export Year (PDF)", "#C62828", export_year_pdf),
                make_option_row(ft.Icons.BACKUP_ROUNDED, "Backup Data", "#1E88E5", backup_data),
                make_option_row(ft.Icons.RESTORE_ROUNDED, "Restore Data", "#1E88E5", restore_data),
                make_sync_option_row(ft.Icons.HELP_OUTLINE_ROUNDED, "Backup & Restore Help", "#C62828", show_backup_help),
                make_sync_option_row(ft.Icons.SCHOOL_ROUNDED, "Replay Tutorial", "#FFD700", lambda e: show_tutorial_screen()),
            ]

            dlg = ft.AlertDialog(
                modal=True,
                bgcolor="#FFFFFF",
                title=ft.Text("More Options", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.ListView(controls=rows, spacing=4),
                    width=270, height=320,
                ),
                actions=[ft.TextButton("Close", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=PURPLE_TEXT))],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dlg)

        mt_more_options_btn = ft.ElevatedButton(
            content=ft.Row(
                [ft.Icon(ft.Icons.MORE_VERT_ROUNDED, size=18, color="white"), ft.Text("More Options", size=13, weight=ft.FontWeight.BOLD, color="white")],
                spacing=6, tight=True,
            ),
            on_click=open_more_options_menu,
            style=ft.ButtonStyle(bgcolor="#4B0082", elevation=6),
        )

        mt_chart_card = ft.Container(
            content=mt_chart_container,
            padding=10, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        )

        mt_category_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("By Category (Net)", color="white", weight=ft.FontWeight.BOLD, size=14),
                            ft.TextButton(
                                content=ft.Text("Set Budget", color="#FFD700", weight=ft.FontWeight.BOLD, size=12),
                                on_click=lambda e: open_budget_dialog(),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    mt_category_list_view,
                ],
                spacing=8,
            ),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        )

        mt_list_card = ft.Container(
            content=ft.Column(
                [ft.Text("Transactions (tap to edit)", color="white", weight=ft.FontWeight.BOLD, size=14), mt_search_input, mt_transactions_list_view],
                spacing=8,
            ),
            padding=15, border_radius=15,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        )

        await refresh_money_ui()

        money_tab_content = ft.Column(
            controls=[
                mt_form, ft.Container(height=10),
                mt_month_nav, ft.Container(height=5),
                mt_summary_container, ft.Container(height=10),
                mt_annual_container, ft.Container(height=10),
                mt_more_options_btn, ft.Container(height=10),
                mt_chart_card, ft.Container(height=10),
                mt_category_card, ft.Container(height=10),
                mt_list_card,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

        # -------------------- TABS (manual, animated, icon-enhanced) --------------------
        tab_labels = ["Housing Upfront", "Salary Management", "Money Tracker"]
        tab_icons = [ft.Icons.HOME_ROUNDED, ft.Icons.WORK_ROUNDED, ft.Icons.ACCOUNT_BALANCE_WALLET_ROUNDED]
        tab_icon_colors = ["#FF8C00", "#E53935", "#1E88E5"]
        tab_contents = [housing_tab_content, salary_tab_content, money_tab_content]
        current_tab_index = {"value": 0}

        tab_content_area = ft.Container(
            content=ft.Container(content=tab_contents[0], padding=ft.Padding(top=15, left=0, right=0, bottom=0)),
            opacity=1,
            scale=1,
            animate_opacity=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
            animate_scale=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
        )

        tab_buttons = []

        def select_tab(idx):
            async def handler(e):
                if current_tab_index["value"] == idx:
                    return
                current_tab_index["value"] = idx

                for i, btn in enumerate(tab_buttons):
                    is_selected = (i == idx)
                    btn.style = ft.ButtonStyle(bgcolor="#FFD700" if is_selected else ft.Colors.with_opacity(0.3, ft.Colors.WHITE))
                    btn.content.controls[1].color = "#4B0082" if is_selected else "white"

                tab_content_area.opacity = 0
                tab_content_area.scale = 0.96
                page.update()
                await asyncio.sleep(0.18)
                tab_content_area.content = ft.Container(content=tab_contents[idx], padding=ft.Padding(top=15, left=0, right=0, bottom=0))
                tab_content_area.opacity = 1
                tab_content_area.scale = 1
                page.update()
            return handler

        tab_icon_containers = []

        for i, label in enumerate(tab_labels):
            icon_container = ft.Container(
                content=ft.Icon(tab_icons[i], size=16, color=tab_icon_colors[i]),
                scale=1.0,
                animate_scale=ft.Animation(700, ft.AnimationCurve.EASE_IN_OUT),
            )
            tab_icon_containers.append(icon_container)
            tab_buttons.append(
                ft.ElevatedButton(
                    content=ft.Row(
                        [icon_container, ft.Text(label, size=12, weight=ft.FontWeight.BOLD, color="#4B0082" if i == 0 else "white")],
                        spacing=4, tight=True,
                    ),
                    style=ft.ButtonStyle(bgcolor="#FFD700" if i == 0 else ft.Colors.with_opacity(0.3, ft.Colors.WHITE)),
                )
            )
        for i, btn in enumerate(tab_buttons):
            btn.on_click = select_tab(i)

        async def animate_tab_icons_loop():
            try:
                while True:
                    for c in tab_icon_containers:
                        c.scale = 1.25
                    page.update()
                    await asyncio.sleep(0.7)
                    for c in tab_icon_containers:
                        c.scale = 1.0
                    page.update()
                    await asyncio.sleep(0.7)
            except Exception:
                pass


        tab_bar_row = ft.Row(tab_buttons, alignment=ft.MainAxisAlignment.CENTER, wrap=True, spacing=6)

        tabs = ft.Column(
            controls=[tab_bar_row, tab_content_area],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
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

        TILT_OVERSCAN = 45

        background_image = ft.Image(
            src="background.png",
            fit=ft.BoxFit.COVER,
            left=-TILT_OVERSCAN, top=-TILT_OVERSCAN, right=-TILT_OVERSCAN, bottom=-TILT_OVERSCAN,
            animate_position=ft.Animation(80, ft.AnimationCurve.EASE_OUT),
        )

        foreground_layer = ft.Container(
            content=main_content, alignment=ft.Alignment(0, -1), padding=10,
            left=0, top=0, right=0, bottom=0,
            animate_position=ft.Animation(80, ft.AnimationCurve.EASE_OUT),
        )

        last_tilt_update = {"time": 0.0}

        def handle_tilt_reading(e: ft.AccelerometerReadingEvent):
            try:
                now = asyncio.get_event_loop().time()
                if now - last_tilt_update["time"] < 0.12:
                    return
                last_tilt_update["time"] = now

                tilt_x = max(-9.8, min(9.8, e.x))
                tilt_y = max(-9.8, min(9.8, e.y))

                bg_shift_x = tilt_x * 3.6
                bg_shift_y = tilt_y * 3.6
                background_image.left = -TILT_OVERSCAN + bg_shift_x
                background_image.right = -TILT_OVERSCAN - bg_shift_x
                background_image.top = -TILT_OVERSCAN + bg_shift_y
                background_image.bottom = -TILT_OVERSCAN - bg_shift_y

                fg_shift_x = tilt_x * -1.2
                fg_shift_y = tilt_y * -1.2
                foreground_layer.left = fg_shift_x
                foreground_layer.right = -fg_shift_x
                foreground_layer.top = fg_shift_y
                foreground_layer.bottom = -fg_shift_y

                logo_offset_x = max(-0.15, min(0.15, tilt_x * 0.02))
                logo_offset_y = max(-0.15, min(0.15, tilt_y * 0.02))
                logo_wrapper.offset = ft.Offset(logo_offset_x, logo_offset_y)

                page.update()
            except Exception:
                pass

        def handle_tilt_error(e: ft.SensorErrorEvent):
            pass

        page.services.append(
            ft.Accelerometer(
                on_reading=handle_tilt_reading,
                on_error=handle_tilt_error,
                interval=ft.Duration(milliseconds=120),
                cancel_on_error=False,
            )
        )

        view_container = ft.Stack(
            controls=[
                background_image,
                foreground_layer,
            ],
            expand=True,
            opacity=0,
            animate_opacity=ft.Animation(400, ft.AnimationCurve.EASE_OUT),
        )

        page.controls.clear()
        page.add(view_container)
        load_banner_ad()
        page.update()
        await asyncio.sleep(0.03)
        view_container.opacity = 1
        page.update()
        asyncio.create_task(animate_logo_pulse_loop())
        asyncio.create_task(animate_logo_spin_loop())
        asyncio.create_task(animate_wave_loop())
        asyncio.create_task(animate_tab_icons_loop())

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
