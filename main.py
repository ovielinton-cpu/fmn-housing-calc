import flet as ft
import json
import os

# 1. Core calculation logic
def calculate_housing_upfront(basic_salary: float, ndic: float, position: str) -> float:
    result_percentage = 45.0 if position == "s" else 40.0
    ndic_calculation = (basic_salary / 100.0) * ndic
    annual_salary = (basic_salary + ndic_calculation) * 12.0
    final_result = (annual_salary / 100.0) * result_percentage
    return round(final_result, 0)

# 2. User Interface Definition
def main(page: ft.Page):
    page.title = "Housing Upfront Calculator"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.scroll = ft.ScrollMode.AUTO
    page.padding = 0  

    # --- RESPONSIVE MOBILE CONFIGURATION ---
    page.head = """
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    """
    # ---------------------------------------

    # --- HEADER SECTION ---
    logo = ft.Image(src="logo.png", width=100, height=100, fit="contain")

    title_text = ft.Text("FMN Housing Upfront Calculator", size=22, weight=ft.FontWeight.BOLD, color="white", text_align=ft.TextAlign.CENTER)
    title_container = ft.Container(
        content=title_text,
        shadow=ft.BoxShadow(spread_radius=1, blur_radius=4, color="black", offset=ft.Offset(2, 2)),
        padding=10
    )

    header_layout = ft.Column(
        controls=[logo, title_container],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=5
    )

    # Greeting Components
    greeting_bg = ft.Text(value="Welcome, Staff!", size=20, weight=ft.FontWeight.BOLD, color="black")
    greeting_fg = ft.Text(value="Welcome, Staff!", size=20, weight=ft.FontWeight.BOLD, color="white")
    greeting_stack = ft.Stack(controls=[ft.Container(content=greeting_bg, left=2, top=2), greeting_fg], height=35)

    dialog_name_input = ft.TextField(label="Enter your name", autofocus=True)
    salary_input = ft.TextField(label="Basic Salary (₦)", keyboard_type=ft.KeyboardType.NUMBER, bgcolor="#FAFAFA", color="black", border_color="#4B0082", border_width=2, focused_border_color="#FFD700")
    ndic_input = ft.TextField(label="NDIC Increment (%)", keyboard_type=ft.KeyboardType.NUMBER, value="0", bgcolor="#FAFAFA", color="black", border_color="#4B0082", border_width=2, focused_border_color="#FFD700")
    position_dropdown = ft.Dropdown(label="Staff Level", options=[ft.dropdown.Option("j", "Junior Staff (40%)"), ft.dropdown.Option("s", "Senior Staff (45%)")], value="j", bgcolor="#FAFAFA", color="black", border_color="#4B0082", border_width=2)

    def save_app_data():
        data_to_save = {"saved_name": dialog_name_input.value, "saved_salary": salary_input.value, "saved_ndic": ndic_input.value, "saved_level": position_dropdown.value}
        with open("saved_data.json", "w") as f: json.dump(data_to_save, f)

    def on_save_name_click(e):
        greeting_text = f"Welcome back, {dialog_name_input.value}! 👋" if dialog_name_input.value.strip() else "Welcome, Staff!"
        greeting_bg.value = greeting_text
        greeting_fg.value = greeting_text
        save_app_data()
        name_popup_dialog.open = False
        page.update()

    name_popup_dialog = ft.AlertDialog(modal=True, title=ft.Text("Personalize"), content=ft.Column(controls=[ft.Text("Please enter your name:"), dialog_name_input], tight=True), actions=[ft.TextButton("Save Name", on_click=on_save_name_click)], actions_alignment=ft.MainAxisAlignment.END)
    page.overlay.append(name_popup_dialog)

    def on_edit_name_click(e):
        name_popup_dialog.open = True
        page.update()

    change_name_btn_3d = ft.Stack(
        controls=[
            ft.Container(content=ft.Text("Change Name", color="white", weight=ft.FontWeight.BOLD, size=14), alignment=ft.Alignment(0, 0), bgcolor="white", width=140, height=40, border_radius=8, left=2, top=2, shadow=ft.BoxShadow(spread_radius=1, blur_radius=12, color="#1A1A1A", offset=ft.Offset(0, 4))),
            ft.Container(content=ft.Text("Change Name", color="black", weight=ft.FontWeight.BOLD, size=14), alignment=ft.Alignment(0, 0), bgcolor="#FFD700", width=140, height=40, border_radius=8, on_click=on_edit_name_click)
        ],
        width=146, height=46
    )

    greeting_row = ft.Row(controls=[greeting_stack, change_name_btn_3d], alignment=ft.MainAxisAlignment.CENTER, spacing=15)

    # Load Saved Data
    show_popup_automatically = True
    if os.path.exists("saved_data.json"):
        try:
            with open("saved_data.json", "r") as f:
                data = json.load(f)
                saved_name = data.get("saved_name", "")
                dialog_name_input.value = saved_name
                if saved_name:
                    greeting_text = f"Welcome back, {saved_name}! 👋"
                    greeting_bg.value = greeting_text
                    greeting_fg.value = greeting_text
                    show_popup_automatically = False
                salary_input.value = data.get("saved_salary", "")
                ndic_input.value = data.get("saved_ndic", "0")
                position_dropdown.value = data.get("saved_level", "j")
        except: pass

    # Results Display
    result_display = ft.Text(spans=[ft.TextSpan("Your housing upfront is: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=20)
    basic_display = ft.Text(spans=[ft.TextSpan("New Basic Salary (Monthly): ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=15)
    NDIC_display = ft.Text(spans=[ft.TextSpan("NDIC Increment (Monthly): ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=15)
    total_display = ft.Text(spans=[ft.TextSpan("Total Annual Salary: ", ft.TextStyle(color="orange", weight=ft.FontWeight.BOLD)), ft.TextSpan("₦0.00", ft.TextStyle(color="green", weight=ft.FontWeight.BOLD))], size=15)

    def on_calculate_click(e):
        try:
            salary = float(salary_input.value) if salary_input.value else 0.0
            ndic = float(ndic_input.value) if ndic_input.value else 0.0
            pos = position_dropdown.value
            final_amount = calculate_housing_upfront(salary, ndic, pos)
            ndic_increment = salary * (ndic / 100.0)
            my_new_basic_salary = salary + ndic_increment
            annual_salary = my_new_basic_salary * 12.0
            result_display.spans[1].text = f"₦{final_amount:,.2f}"
            basic_display.spans[1].text = f"₦{my_new_basic_salary:,.2f}"
            NDIC_display.spans[1].text = f"₦{ndic_increment:,.2f}"
            total_display.spans[1].text = f"₦{annual_salary:,.2f}"
        except ValueError:
            result_display.spans[1].text = "Invalid"
        save_app_data()
        page.update()

    calc_button_3d = ft.Stack(
        controls=[
            ft.Container(content=ft.Text("Calculate Upfront", color="black", weight=ft.FontWeight.BOLD, size=15), alignment=ft.Alignment(0, 0), bgcolor="black", width=180, height=42, border_radius=8, left=2, top=2, shadow=ft.BoxShadow(spread_radius=1, blur_radius=14, color="#000000", offset=ft.Offset(0, 5))),
            ft.Container(content=ft.Text("Calculate Upfront", color="black", weight=ft.FontWeight.BOLD, size=15), alignment=ft.Alignment(0, 0), bgcolor="#FFD700", width=180, height=42, border_radius=8, on_click=on_calculate_click)
        ],
        width=186, height=48
    )

    form_border_side = ft.BorderSide(width=2, color="#D4D4CE")
    form_fields_container = ft.Container(
        content=ft.Column(controls=[salary_input, ndic_input, position_dropdown, ft.Divider(height=15, color="transparent"), calc_button_3d], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=15),
        padding=25, bgcolor="#F5F5F0", border_radius=15, border=ft.Border(top=form_border_side, bottom=form_border_side, left=form_border_side, right=form_border_side)
    )

    app_layout_content = ft.Column(
        controls=[
            header_layout, greeting_row, ft.Divider(color="white"),
            ft.Card(content=form_fields_container, elevation=20),
            ft.Container(padding=20, bgcolor="#FFFFFF", border_radius=12, width=350,
                border=ft.Border(top=form_border_side, bottom=form_border_side, left=form_border_side, right=form_border_side),
                content=ft.Column([result_display, ft.Divider(height=5, color="#D4D4CE"), basic_display, NDIC_display, total_display], spacing=8)
            )
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )

    page.add(ft.Container(content=app_layout_content, gradient=ft.LinearGradient(rotation=1.57, colors=["#4B0082", "#E6E6FA"]), padding=20))

    if show_popup_automatically:
        name_popup_dialog.open = True
        page.update()

ft.app(target=main, assets_dir="assets")