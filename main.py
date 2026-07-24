import flet as ft
import hashlib

async def build_ui(page: ft.Page):
    page.title = "Housing-Salary Calc"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.adaptive = True
    page.padding = 0

    DARK_TEXT = "#222222"
    PURPLE_TEXT = "#4B0082"

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

    async def close_terms(e):
        await page.shared_preferences.set("terms_accepted", True)
        page.pop_dialog()
        await check_activation()

    # --- ACTIVATION CODE SYSTEM ---
    SECRET_WORD = "BadSeniorMan"

    def expected_chunk2(chunk1: str) -> str:
        digest = hashlib.sha256((chunk1.upper() + SECRET_WORD).encode()).hexdigest()
        return digest[:8].upper()

    def is_valid_code(code: str) -> bool:
        code = code.strip().upper().replace(" ", "")
        if "-" not in code:
            return False
        parts = code.split("-")
        if len(parts) != 2:
            return False
        chunk1, chunk2 = parts
        return expected_chunk2(chunk1) == chunk2

    async def check_activation():
        try:
            activated = await page.shared_preferences.get("activated")
        except Exception:
            activated = False

        if activated:
            existing_name = await page.shared_preferences.get("user_name")
            if not existing_name:
                open_name_dialog()
            return

        error_text = ft.Text("", color="red", size=13)

        async def on_activate_click(e):
            if is_valid_code(code_field.value or ""):
                await page.shared_preferences.set("activated", True)
                page.pop_dialog()
                existing_name = await page.shared_preferences.get("user_name")
                if not existing_name:
                    open_name_dialog()
            else:
                error_text.value = "Invalid code. Please check and try again."
                page.update()

        code_field = ft.TextField(
            label="Activation Code",
            autofocus=True,
            bgcolor="#FFFFFF",
            color=PURPLE_TEXT,
            label_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        )

        activation_dialog = ft.AlertDialog(
            modal=True,
            bgcolor="#FFFFFF",
            title=ft.Text("Activate App", color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "This app requires an activation code. Please enter the code you received after payment.",
                            color=DARK_TEXT, size=14
                        ),
                        code_field,
                        error_text,
                    ],
                    tight=True,
                    spacing=12,
                ),
                width=300,
                padding=10,
            ),
            actions=[ft.TextButton("Activate", on_click=on_activate_click, style=ft.ButtonStyle(color=PURPLE_TEXT))],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(activation_dialog)

    terms_content = ft.Column(
        [
            ft.Text("Terms and Conditions", size=18, weight=ft.FontWeight.BOLD, color=PURPLE_TEXT),
            ft.Text(
                "1. Purpose: This application is provided as a general tool to help staff of any organization estimate their housing upfront payments, based on figures and rates you enter yourself.\n\n"
                "2. Accuracy: All calculations are estimates based on the information you provide. These figures should be verified against your own organization's official payroll policy.\n\n"
                "3. Disclaimer: The developer is not responsible for any financial decisions made based on these calculations. Please consult with your HR department for official confirmation.\n\n"
                "4. Privacy: No personal data or salary information is stored, transmitted, or shared externally by this application. Everything you enter stays on your device.",
                color=DARK_TEXT,
                size=14
            ),
        ],
        scroll=ft.ScrollMode.AUTO,
        height=300,
        spacing=10
    )

    def decline_terms(e):
        page.pop_dialog()
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

    terms_dialog = ft.AlertDialog(
        modal=True,
        bgcolor="#FFFFFF",
        title=ft.Text("Welcome & Agreement", weight=ft.FontWeight.BOLD, color=PURPLE_TEXT),
        content=ft.Container(content=terms_content, width=320, height=350),
        actions=[
            ft.TextButton("I Agree", on_click=close_terms, style=ft.ButtonStyle(color=PURPLE_TEXT)),
            ft.TextButton("I Don't Agree", on_click=decline_terms, style=ft.ButtonStyle(color="red")),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    logo_image = ft.Image(
        src="logo.png",
        width=90,
        height=90,
        fit=ft.BoxFit.CONTAIN
    )

    header_text = ft.Container(
        content=ft.Text(
            "Housing-Salary Calc",
            size=22,
            weight=ft.FontWeight.BOLD,
            color="white",
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
        value=last_org,
        bgcolor="#FFFFFF",
        border_color=PURPLE_TEXT,
        color=PURPLE_TEXT,
        text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        on_change=on_org_change
    )

    salary_input = ft.TextField(
        value=last_salary,
        keyboard_type=ft.KeyboardType.NUMBER,
        bgcolor="#FFFFFF",
        border_color=PURPLE_TEXT,
        color=PURPLE_TEXT,
        hint_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        on_change=on_salary_change
    )

    increment_label_input = ft.TextField(
        value=last_increment_label,
        bgcolor="#FFFFFF",
        border_color=PURPLE_TEXT,
        color=PURPLE_TEXT,
        text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        on_change=on_increment_label_change
    )

    increment_input = ft.TextField(
        value=last_increment_pct,
        keyboard_type=ft.KeyboardType.NUMBER,
        bgcolor="#FFFFFF",
        border_color=PURPLE_TEXT,
        color=PURPLE_TEXT,
        text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        on_change=on_increment_change
    )

    rate_input = ft.TextField(
        value=last_rate_pct,
        keyboard_type=ft.KeyboardType.NUMBER,
        bgcolor="#FFFFFF",
        border_color=PURPLE_TEXT,
        color=PURPLE_TEXT,
        text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        on_change=on_rate_change
    )

    def field_with_caption(caption_text, field):
        return ft.Column(
            [
                ft.Text(caption_text, color="#FF3B30", weight=ft.FontWeight.BOLD, size=12),
                field,
            ],
            spacing=2,
            tight=True,
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

    form_container = ft.Container(
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
        padding=20,
        border_radius=15,
        bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.with_opacity(0.20, ft.Colors.BLACK))
    )

    results_container = ft.Container(
        content=ft.Column([result_upfront, ft.Divider(height=1, color="#4B0082"), result_basic, result_increment, result_total], spacing=8, tight=True),
        padding=15,
        border_radius=15,
        bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
        border=ft.Border(ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700")),
        shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK))
    )

    content_wrapper = ft.Container(
        content=ft.Column(
            controls=[header_container, greeting_row, form_container, ft.Container(height=10), results_container],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=5,
        ),
        width=400,
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
            ft.Image(
                src="background.png",
                fit=ft.BoxFit.COVER,
                left=0,
                top=0,
                right=0,
                bottom=0,
            ),
            ft.Container(
                content=main_content,
                alignment=ft.Alignment(0, -1),
                padding=10,
                left=0,
                top=0,
                right=0,
                bottom=0,
            ),
        ],
        expand=True
    )

    page.add(view_container)

    try:
        terms_already_accepted = await page.shared_preferences.get("terms_accepted")
    except Exception:
        terms_already_accepted = False

    if not terms_already_accepted:
        page.show_dialog(terms_dialog)
    else:
        await check_activation()

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
    
