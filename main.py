import flet as ft
import os
import json

def main(page: ft.Page):
    page.title = "Housing Upfront Calculator"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.adaptive = True
    page.padding = 0

    DARK_TEXT = "#222222"
    PURPLE_TEXT = "#4B0082"

    greeting_name = ft.Text("Staff!", size=20, weight=ft.FontWeight.BOLD, color="white")

    def open_name_dialog(e=None):
        def save_name(e):
            new_name = name_field.value
            greeting_name.value = f"{new_name}! 👋" if new_name else "Staff!"
            page.client_storage.set("user_name", new_name)
            page.close(name_dialog)
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
        page.open(name_dialog)

    change_btn = ft.ElevatedButton("Change Name", on_click=open_name_dialog, style=ft.ButtonStyle(bgcolor="#FFD700", color="#4B0082"))

    greeting_row = ft.Row(
        controls=[ft.Text("Welcome back,", size=20, color="white"), greeting_name, change_btn],
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=10,
        wrap=True,
    )

    def close_terms(e):
        page.client_storage.set("terms_accepted", True)
        page.close(terms_dialog)
        if not page.client_storage.get("user_name"):
            open_name_dialog()

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

    terms_dialog = ft.AlertDialog(
        modal=True,
        bgcolor="#FFFFFF",
        title=ft.Text("Welcome & Agreement", weight=ft.FontWeight.BOLD, color=PURPLE_TEXT),
        content=ft.Container(content=terms_content, width=320, height=350),
        actions=[
            ft.TextButton("I Agree", on_click=close_terms, style=ft.ButtonStyle(color=PURPLE_TEXT)),
            ft.TextButton("I Don't Agree", on_click=lambda e: page.window.close(), style=ft.ButtonStyle(color="red")),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    logo_image = ft.Image(
        src="logo.png",
        width=90,
        height=90,
        fit="contain"
    )

    header_text = ft.Text(
        "Housing Upfront Calculator",
        size=22,
        weight=ft.FontWeight.BOLD,
        color="white",
        text_align=ft.TextAlign.CENTER
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
        saved_name = page.client_storage.get("user_name")
        if saved_name:
            greeting_name.value = f"{saved_name}! 👋"
    except Exception:
        pass

    def load_saved(key, default=""):
        try:
            val = page.client_storage.get(key)
            return val if val else default
        except Exception:
            return default

    last_org = load_saved("last_org", "")
    last_salary = load_saved("last_salary", "")
    last_increment_label = load_saved("last_increment_label", "Salary Increment")
    last_increment_pct = load_saved("last_increment_pct", "0")
    last_rate_pct = load_saved("last_rate_pct", "40")

    def save_field(key, value):
        page.client_storage.set(key, value)

    org_input = ft.TextField(
        label="Company / Organization Name (optional)",
        value=last_org,
        bgcolor="#FFFFFF",
        border_color=PURPLE_TEXT,
        color=PURPLE_TEXT,
        label_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        on_change=lambda e: save_field("last_org", org_input.value)
    )

    salary_input = ft.TextField(
        label="Basic Salary (₦)",
        value=last_salary,
        keyboard_type=ft.KeyboardType.NUMBER,
        bgcolor="#FFFFFF",
        border_color=PURPLE_TEXT,
        color=PURPLE_TEXT,
        hint_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        label_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        on_change=lambda e: save_field("last_salary", salary_input.value)
    )

    increment_label_input = ft.TextField(
        label="Increment Name (e.g. NDIC, Housing Allowance, etc.)",
        value=last_increment_label,
        bgcolor="#FFFFFF",
        border_color=PURPLE_TEXT,
        color=PURPLE_TEXT,
        label_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        on_change=lambda e: save_field("last_increment_label", increment_label_input.value)
    )

    increment_input = ft.TextField(
        label="Increment (%)",
        value=last_increment_pct,
        keyboard_type=ft.KeyboardType.NUMBER,
        bgcolor="#FFFFFF",
        border_color=PURPLE_TEXT,
        color=PURPLE_TEXT,
        label_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        on_change=lambda e: save_field("last_increment_pct", increment_input.value)
    )

    rate_input = ft.TextField(
        label="Housing Upfront Rate (%)",
        value=last_rate_pct,
        keyboard_type=ft.KeyboardType.NUMBER,
        bgcolor="#FFFFFF",
        border_color=PURPLE_TEXT,
        color=PURPLE_TEXT,
        label_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        text_style=ft.TextStyle(color=PURPLE_TEXT, weight=ft.FontWeight.BOLD),
        on_change=lambda e: save_field("last_rate_pct", rate_input.value)
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
            controls=[org_input, salary_input, increment_label_input, increment_input, rate_input, calc_btn],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=15, tight=True
        ),
        padding=20,
        border_radius=15,
        bgcolor="#F5F5F0",
        shadow=ft.BoxShadow(blur_radius=10, color="#333333")
    )
    form_card = ft.Card(content=form_container, elevation=5)

    results_container = ft.Container(
        content=ft.Column([result_upfront, ft.Divider(height=1, color="#4B0082"), result_basic, result_increment, result_total], spacing=8, tight=True),
        padding=15,
        border_radius=15,
        bgcolor="#FFFFFF",
        border=ft.Border(ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700"), ft.BorderSide(2, "#FFD700")),
        shadow=ft.BoxShadow(blur_radius=5, color="#333333")
    )

    content_wrapper = ft.Container(
        content=ft.Column(
            controls=[header_container, greeting_row, form_card, ft.Container(height=10), results_container],
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

    view_container = ft.Container(
        content=main_content,
        gradient=ft.LinearGradient(begin=ft.Alignment(0, -1), end=ft.Alignment(0, 1), colors=["#4B0082", "#E6E6FA"]),
        alignment=ft.Alignment(0, -1),
        padding=10,
        expand=True
    )

    page.add(view_container)

    try:
        terms_already_accepted = page.client_storage.get("terms_accepted")
    except Exception:
        terms_already_accepted = False

    if not terms_already_accepted:
        page.open(terms_dialog)
    elif not page.client_storage.get("user_name"):
        open_name_dialog()

if __name__ == "__main__":
    ft.app(target=main, view=ft.AppView.WEB_BROWSER)
