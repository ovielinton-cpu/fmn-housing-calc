import flet as ft
import os
import json

def main(page: ft.Page):
    page.title = "FMN Housing Upfront Calculator"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.adaptive = True
    page.padding = 0 

    # High-contrast color rule for clear visibility (Fixes faint text/labels)
    DARK_TEXT = "#222222"

    # --- 3. TERMS AND CONDITIONS LOGIC ---
    def close_terms(e):
        terms_dialog.open = False
        page.update()

    terms_content = ft.Column(
        [
            ft.Text("Terms and Conditions", size=18, weight=ft.FontWeight.BOLD, color=DARK_TEXT),
            ft.Text(
                "1. Purpose: This application is provided as a tool to assist FMN staff in estimating their Housing Upfront payments.\n\n"
                "2. Accuracy: All calculations are estimates based on the information provided. These figures should be verified against official FMN payroll policies.\n\n"
                "3. Disclaimer: The developer is not responsible for any financial decisions made based on these calculations. Please consult with your HR department for official confirmation.\n\n"
                "4. Privacy: No personal data or salary information is stored, transmitted, or shared externally by this application.",
                color=DARK_TEXT,
                size=14
            ),
        ],
        scroll=ft.ScrollMode.AUTO, # Requires scrolling down
        height=300,
        spacing=10
    )

    terms_dialog = ft.AlertDialog(
        modal=True, # Forces the user to interact
        title=ft.Text("Welcome & Agreement", weight=ft.FontWeight.BOLD),
        content=ft.Container(content=terms_content, width=320, height=350),
        actions=[
            ft.TextButton("I Agree", on_click=close_terms, style=ft.ButtonStyle(color="#4B0082")),
            ft.TextButton("I Don't Agree", on_click=lambda e: page.window_close(), style=ft.ButtonStyle(color="red")),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def show_terms_on_startup(page):
        page.dialog = terms_dialog
        terms_dialog.open = True
        page.update()

    # --- 1. HEADER SETUP (Fixing the Logo path) ---
    logo_image = ft.Image(
        src="assets/logo.png",  # Correctly pointing to your assets directory
        width=90, 
        height=90, 
        fit=ft.ImageFit.CONTAIN
    )
    
    header_text = ft.Text(
        "FMN Housing Upfront Calculator",
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
        padding=ft.padding.only(top=20, bottom=5),
        width=350,
    )

    # --- GREETING SECTION ---
    greeting_name = ft.Text("Staff!", size=20, weight=ft.FontWeight.BOLD, color="white")
    
    def on_change_click(e):
        def save_name(e):
            new_name = name_field.value
            greeting_name.value = f"{new_name}! 👋" if new_name else "Staff!"
            data = {"user_name": new_name}
            with open("user_prefs.json", "w") as f:
                json.dump(data, f)
            dialog.open = False
            page.update()

        name_field = ft.TextField(label="Your Name", value=greeting_name.value.split("!")[0] if "👋" in greeting_name.value else "", autofocus=True)
        dialog = ft.AlertDialog(
            title=ft.Text("Update Name"),
            content=name_field,
            actions=[ft.TextButton("Save", on_click=save_name)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.dialog = dialog
        dialog.open = True
        page.update()

    try:
        if os.path.exists("user_prefs.json"):
            with open("user_prefs.json", "r") as f:
                loaded_data = json.load(f)
                if loaded_data.get("user_name"):
                    greeting_name.value = f"{loaded_data['user_name']}! 👋"
    except:
        pass

    change_btn = ft.ElevatedButton("Change", on_click=on_change_click, style=ft.ButtonStyle(bgcolor="#FFD700", color="#4B0082"))

    greeting_row = ft.Row(
        controls=[ft.Text("Welcome back,", size=20, color="white"), greeting_name, change_btn],
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=10
    )

    # --- 2. CALCULATOR FORM (Fixing faint text/labels) ---
    salary_input = ft.TextField(
        label="Basic Salary (₦)", 
        keyboard_type=ft.KeyboardType.NUMBER, 
        bgcolor="#FFFFFF", 
        border_color="#4B0082",
        color=DARK_TEXT,
        label_style=ft.TextStyle(color=DARK_TEXT)
    )
    ndic_input = ft.TextField(
        label="NDIC Increment (%)", 
        value="0", 
        keyboard_type=ft.KeyboardType.NUMBER, 
        bgcolor="#FFFFFF", 
        border_color="#4B0082",
        color=DARK_TEXT,
        label_style=ft.TextStyle(color=DARK_TEXT)
    )
    level_dropdown = ft.Dropdown(
        label="Staff Level",
        options=[
            ft.dropdown.Option("junior", "Junior Staff (40%)"),
            ft.dropdown.Option("senior", "Senior Staff (45%)")
        ],
        value="junior",
        bgcolor="#FFFFFF",
        border_color="#4B0082",
        color=DARK_TEXT,
        label_style=ft.TextStyle(color=DARK_TEXT)
    )

    # --- 4. RESULTS DISPLAY (Cleaned & Updated to "NDIC Addition") ---
    result_upfront = ft.Text(spans=[ft.TextSpan("Upfront: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=18)
    result_basic = ft.Text(spans=[ft.TextSpan("Annual Basic: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
    result_ndic = ft.Text(spans=[ft.TextSpan("NDIC Addition: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)
    result_total = ft.Text(spans=[ft.TextSpan("Total Gross: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=14)

    def on_calculate_click(e):
        try:
            salary = float(salary_input.value)
            ndic_pct = float(ndic_input.value)
            level = level_dropdown.value
            
            rate = 0.40 if level == "junior" else 0.45
            
            annual_basic = salary * 12.0
            ndic_amount = annual_basic * (ndic_pct / 100.0)
            annual_total = annual_basic + ndic_amount
            upfront_amount = annual_total * rate
            
            result_upfront.spans[1].text = f"₦{upfront_amount:,.2f}"
            result_basic.spans[1].text = f"₦{annual_basic:,.2f}"
            result_ndic.spans[1].text = f"₦{ndic_amount:,.2f}"
            result_total.spans[1].text = f"₦{annual_total:,.2f}"
            
            page.update()
        except ValueError:
            result_upfront.spans[1].text = "Invalid Input"
            page.update()

    calc_btn = ft.ElevatedButton("Calculate Upfront", on_click=on_calculate_click, style=ft.ButtonStyle(bgcolor="#FFD700", color="#4B0082", text_style=ft.TextStyle(weight=ft.FontWeight.BOLD)))

    form_container = ft.Container(
        content=ft.Column(controls=[salary_input, ndic_input, level_dropdown, calc_btn], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=15, tight=True),
        padding=20,
        border_radius=15,
        bgcolor="#F5F5F0",
        width=350,
        shadow=ft.BoxShadow(blur_radius=10, color="#333333")
    )
    form_card = ft.Card(content=form_container, elevation=5)

    results_container = ft.Container(
        content=ft.Column([result_upfront, ft.Divider(height=1, color="#4B0082"), result_basic, result_ndic, result_total], spacing=8, tight=True),
        padding=15,
        border_radius=15,
        bgcolor="#FFFFFF",
        width=350,
        border=ft.Border(top=ft.BorderSide(2, "#FFD700"), bottom=ft.BorderSide(2, "#FFD700"), left=ft.BorderSide(2, "#FFD700"), right=ft.BorderSide(2, "#FFD700")),
        shadow=ft.BoxShadow(blur_radius=5, color="#333333")
    )

    main_content = ft.Column(
        controls=[header_container, greeting_row, form_card, ft.Container(height=10), results_container],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=5,
        expand=True
    )

    view_container = ft.Container(
        content=main_content,
        gradient=ft.LinearGradient(begin=ft.alignment.top_center, end=ft.alignment.bottom_center, colors=["#4B0082", "#E6E6FA"]),
        alignment=ft.alignment.top_center,
        padding=10,
        expand=True
    )

    page.add(view_container)
    
    # Fire up the Terms pop-up task immediately upon app opening
    page.run_task(show_terms_on_startup, page)

if __name__ == "__main__":
    ft.app(target=main)
    
