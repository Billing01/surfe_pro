import time
import re
import base64
import hmac
import hashlib
import struct

from urllib.parse import quote

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError
)


# ============================================================
# CONFIGURATION
# ============================================================

EMAIL = "redja1914@gmail.com"
PASSWORD = "Decent@5013"
TOTP_SECRET = "SSA2DJNJHIP6K6A5"

LOGIN_URL = "https://surfe.pro/login"

API_MAIN = "https://f-con.vipb.top/get.php?main="
API_SEC = "https://f-con.vipb.top/get.php?sec="

CHECK_INTERVAL = 120

MOBILE_WIDTH = 390
MOBILE_HEIGHT = 844


# ============================================================
# LOGGING
# ============================================================

def log(message):

    print(
        f"[{time.strftime('%H:%M:%S')}] {message}",
        flush=True
    )


# ============================================================
# TOTP GENERATOR
# ============================================================

def generate_totp(secret):

    key = base64.b32decode(secret.upper())

    counter = int(time.time()) // 30

    msg = struct.pack(">Q", counter)

    digest = hmac.new(
        key,
        msg,
        hashlib.sha1
    ).digest()

    offset = digest[-1] & 0x0F

    binary = struct.unpack(
        ">I",
        digest[offset:offset + 4]
    )[0] & 0x7FFFFFFF

    return str(binary % 1000000).zfill(6)


# ============================================================
# WAIT FOR ELEMENT
# ============================================================

def wait_for_element(locator, timeout=60):

    start = time.monotonic()

    while True:

        try:

            for i in range(locator.count()):

                element = locator.nth(i)

                if element.is_visible():
                    return element

        except Exception:
            pass

        if timeout is not None:

            if time.monotonic() - start >= timeout:

                raise PlaywrightTimeoutError(
                    "Element did not become visible."
                )

        time.sleep(0.3)


# ============================================================
# LOGIN
# ============================================================

def login(page):

    log("Opening Surfe login page...")

    page.goto(
        LOGIN_URL,
        wait_until="domcontentloaded"
    )

    log("Waiting for email field...")

    email = wait_for_element(
        page.locator("#login")
    )

    email.fill(EMAIL)

    log("Entering password...")

    password = wait_for_element(
        page.locator("#password")
    )

    password.fill(PASSWORD)

    log("Submitting credentials...")

    page.locator(
        'button[type="submit"]'
    ).first.click()

    log("Waiting for 2FA...")

    otp_fields = page.locator(
        'div.react-code-input input[type="number"]'
    )

    wait_for_element(otp_fields)

    while otp_fields.count() < 6:
        time.sleep(0.3)

    code = generate_totp(TOTP_SECRET)

    log("Entering 2FA code...")

    for i, digit in enumerate(code):

        otp_fields.nth(i).fill(digit)

    log("Submitting 2FA...")

    page.locator(
        'button[type="submit"]'
    ).last.click()

    try:

        page.wait_for_url(
            lambda url: "/login" not in url,
            timeout=60000
        )

        log("Login successful!")

    except PlaywrightTimeoutError:

        if page.locator("#login").count() > 0:

            raise RuntimeError(
                "Authentication failed."
            )

        log("Continuing after authentication redirect timeout.")

    log("Current URL: " + page.url)


# ============================================================
# AD UNITS TAB
# ============================================================

def click_ad_units_tab(page, timeout=90):

    log("Looking for Ad units tab...")

    tab = page.locator(
        'div[class*="_SiteTabs__Tab_"]'
    ).filter(
        has_text=re.compile(
            r"^\s*Ad units\s*$"
        )
    )

    start = time.monotonic()

    while time.monotonic() - start < timeout:

        try:

            for i in range(tab.count() - 1, -1, -1):

                element = tab.nth(i)

                if element.is_visible():

                    element.click(timeout=5000)

                    page.wait_for_timeout(1000)

                    log("Ad units tab opened.")

                    return

        except Exception:
            pass

        time.sleep(0.5)

    raise PlaywrightTimeoutError(
        "Ad units tab not found."
    )


# ============================================================
# PARSING HELPERS
# ============================================================

def extract_integer(value):

    if not value:
        return None

    value = value.replace(",", "")

    match = re.search(
        r"-?\d+",
        value
    )

    return int(match.group()) if match else None


def extract_percentage(value):

    if not value:
        return None

    match = re.search(
        r"-?\d+(?:\.\d+)?",
        value.replace(",", "")
    )

    return float(match.group()) if match else None


def extract_identifier(value):

    match = re.search(
        r"\d+",
        value
    )

    return match.group() if match else None


# ============================================================
# READ AD UNITS
# ============================================================

def get_ad_units(page):

    units = []

    titles = page.locator(
        'span[class*="__Title__Name"]'
    )

    for i in range(titles.count()):

        try:

            title = titles.nth(i)

            if not title.is_visible():
                continue

            identifier = extract_identifier(
                title.inner_text().strip()
            )

            if not identifier:
                continue

            # Title -> Header -> Ad unit card

            card = title.locator(
                "xpath=../../.."
            )

            stats = {}

            stat_items = card.locator(
                'div[class*="__Stats__Item_"]'
            )

            for j in range(stat_items.count()):

                item = stat_items.nth(j)

                name_locator = item.locator(
                    'div[class*="__Name_"]'
                )

                value_locator = item.locator(
                    'div[class*="__Value_"]'
                )

                if not name_locator.count():
                    continue

                if not value_locator.count():
                    continue

                name = name_locator.first.inner_text().strip()

                value = value_locator.first.inner_text().strip()

                stats[name] = value

            quality_raw = stats.get(
                "Quality",
                ""
            ).strip()

            quality_empty = quality_raw in (
                "-",
                "—",
                ""
            )

            units.append({

                "id": identifier,

                "quality": extract_percentage(
                    quality_raw
                ),

                "quality_raw": quality_raw,

                "quality_empty": quality_empty,

                "impressions": extract_integer(
                    stats.get("Impressions", "")
                ),

                "clicks": extract_integer(
                    stats.get("Clicks", "")
                ),

                "ctr": extract_percentage(
                    stats.get("CTR", "")
                ),

                "card": card

            })

        except Exception as error:

            log(
                f"Error reading ad unit: {error}"
            )

    return units


# ============================================================
# FIND AD UNIT BY ID
# ============================================================

def find_ad_unit(page, identifier):

    titles = page.locator(
        'span[class*="__Title__Name"]'
    )

    for i in range(titles.count()):

        try:

            title = titles.nth(i)

            if not title.is_visible():
                continue

            current_id = extract_identifier(
                title.inner_text()
            )

            if current_id == str(identifier):

                return title.locator(
                    "xpath=../../.."
                )

        except Exception:
            continue

    return None


# ============================================================
# HTTP REQUESTS
# ============================================================

def send_request(context, endpoint, identifier):

    url = endpoint + quote(str(identifier))

    log(f"Sending request: {url}")

    try:

        response = context.request.get(
            url,
            timeout=20000
        )

        log(
            f"HTTP status: {response.status}"
        )

        try:

            log(
                "Response: " + response.text()[:500]
            )

        except Exception:
            pass

    except Exception as error:

        log(
            f"HTTP request failed: {error}"
        )


# ============================================================
# DELETE AD UNIT
# ============================================================

def delete_ad_unit(page, identifier):

    log(
        f"Attempting to delete #{identifier}"
    )

    card = find_ad_unit(
        page,
        identifier
    )

    if card is None:

        log("Ad unit no longer exists.")

        return False

    try:

        # ----------------------------------------
        # CLICK DELETE ACTION
        # ----------------------------------------

        delete_action = card.locator(
            'div[class*="__Options__Link_"]'
        ).filter(
            has_text=re.compile(
                r"^\s*Delete\s*$"
            )
        )

        delete_action = wait_for_element(
            delete_action,
            timeout=15
        )

        delete_action.scroll_into_view_if_needed()

        delete_action.click(
            timeout=10000
        )

        log(
            "Delete clicked. Waiting for modal..."
        )

        # ----------------------------------------
        # FIND CONFIRMATION MODAL
        # ----------------------------------------

        popup = page.locator(
            'div[class*="_Popup__Buttons_"]'
        )

        wait_for_element(
            popup,
            timeout=20
        )

        confirm_button = popup.locator(
            "button"
        ).filter(
            has_text=re.compile(
                r"^\s*Delete\s*$"
            )
        )

        confirm_button = wait_for_element(
            confirm_button,
            timeout=15
        )

        log(
            "Confirmation modal detected."
        )

        # ----------------------------------------
        # CONFIRM DELETION
        # ----------------------------------------

        confirm_button.click(
            timeout=15000
        )

        log(
            "Confirmation button clicked."
        )

        # ----------------------------------------
        # VERIFY DELETION
        # ----------------------------------------

        start = time.monotonic()

        while time.monotonic() - start < 30:

            if find_ad_unit(page, identifier) is None:

                log(
                    f"Successfully deleted #{identifier}"
                )

                return True

            time.sleep(0.5)

        log(
            f"Could not confirm deletion of #{identifier}"
        )

        return False

    except Exception as error:

        log(
            f"Deletion error for #{identifier}: {error}"
        )

        return False


# ============================================================
# CLICK CREATE BUTTON
# ============================================================

def click_create_button(page):

    log("Looking for Create button...")

    # Exact CSS classes supplied.

    create_button = page.locator(
        'div[class*="_CreateButton_prx0z_37"]'
        '[class*="_CreateButton_24_prx0z_88"]'
    )

    # Fallback selector.

    if create_button.count() == 0:

        create_button = page.locator(
            'div[class*="_CreateButton_"]'
        )

    button = wait_for_element(
        create_button,
        timeout=30
    )

    button.scroll_into_view_if_needed()

    try:

        button.click(
            timeout=10000
        )

    except Exception as error:

        log(
            f"Normal Create click failed: {error}"
        )

        log(
            "Retrying Create with force click..."
        )

        button.click(
            force=True,
            timeout=10000
        )

    log(
        "Create button clicked successfully."
    )

    page.wait_for_timeout(500)


# ============================================================
# CREATE NEW AD UNIT
# ============================================================

def create_ad_unit(page, context, existing_ids):

    log("=" * 45)
    log("STARTING AD UNIT CREATION")
    log("=" * 45)

    # ----------------------------------------
    # CREATE BUTTON
    # ----------------------------------------

    click_create_button(page)

    # ----------------------------------------
    # AMOUNT DROPDOWN
    # ----------------------------------------

    log("Opening Amount dropdown...")

    amount_dropdown = page.locator(
        'div[class*="_Editor__Dropdown_"]'
    ).filter(
        has_text=re.compile(
            r"\bAmount\b"
        )
    )

    wait_for_element(
        amount_dropdown,
        timeout=20
    ).click()

    # ----------------------------------------
    # SELECT AMOUNT 4
    # ----------------------------------------

    log("Selecting Amount 4...")

    amount_option = page.locator(
        'div[class*="_Dropdown__Item_"]'
    ).filter(
        has_text=re.compile(
            r"^\s*4\s*$"
        )
    )

    wait_for_element(
        amount_option,
        timeout=20
    ).click()

    # ----------------------------------------
    # ALIGNMENT DROPDOWN
    # ----------------------------------------

    log("Opening Alignment dropdown...")

    alignment_dropdown = page.locator(
        'div[class*="_Editor__Dropdown_"]'
    ).filter(
        has_text=re.compile(
            r"\bAlignment\b"
        )
    )

    wait_for_element(
        alignment_dropdown,
        timeout=20
    ).click()

    # ----------------------------------------
    # SELECT COLUMN
    # ----------------------------------------

    log("Selecting Column...")

    column_option = page.locator(
        'div[class*="_Dropdown__Item__Label_"]'
    ).filter(
        has_text=re.compile(
            r"^\s*Column\s*$"
        )
    )

    wait_for_element(
        column_option,
        timeout=20
    ).click()

    # ----------------------------------------
    # DONE BUTTON
    # ----------------------------------------

    log("Looking for Done button...")

    done_button = page.locator(
        'button[class*="_Button_blue_"]'
    ).filter(
        has_text=re.compile(
            r"^\s*Done\s*$"
        )
    )

    done_button = wait_for_element(
        done_button,
        timeout=20
    )

    done_button.scroll_into_view_if_needed()

    try:

        done_button.click(
            timeout=15000
        )

    except Exception as error:

        log(
            f"Normal Done click failed: {error}"
        )

        log(
            "Retrying Done with force click..."
        )

        done_button.click(
            force=True,
            timeout=10000
        )

    log(
        "Done clicked successfully."
    )

    # ----------------------------------------
    # WAIT FOR CREATION
    # ----------------------------------------

    page.wait_for_timeout(1500)

    click_ad_units_tab(
        page,
        timeout=30
    )

    log(
        "Searching for newly created ad unit..."
    )

    start = time.monotonic()

    refreshed = False

    while time.monotonic() - start < 60:

        try:

            units = get_ad_units(page)

            new_units = [

                unit for unit in units

                if unit["id"] not in existing_ids

                and unit["impressions"] == 0

                and unit["clicks"] == 0

                and unit["ctr"] == 0

            ]

            if new_units:

                new_unit = new_units[-1]

                identifier = new_unit["id"]

                log(
                    f"New ad unit identified: #{identifier}"
                )

                send_request(
                    context,
                    API_SEC,
                    identifier
                )

                return identifier

            if not refreshed:

                if time.monotonic() - start >= 15:

                    log(
                        "Refreshing to find new ad unit..."
                    )

                    page.reload(
                        wait_until="domcontentloaded",
                        timeout=60000
                    )

                    click_ad_units_tab(
                        page,
                        timeout=30
                    )

                    refreshed = True

        except Exception as error:

            log(
                f"Waiting for new ad unit: {error}"
            )

        time.sleep(2)

    log(
        "WARNING: New ad unit could not be identified."
    )

    return None


# ============================================================
# PROCESS AD UNITS
# ============================================================

def process_ad_units(page, context):

    log("")
    log("=" * 55)
    log("STARTING AD UNIT CHECK")
    log("=" * 55)

    units = get_ad_units(page)

    log(
        f"Found {len(units)} ad unit(s)."
    )

    # ----------------------------------------
    # NO AD UNITS
    # ----------------------------------------

    if not units:

        log("No ad units found.")

        create_ad_unit(
            page,
            context,
            set()
        )

        return

    # ----------------------------------------
    # DISPLAY INFORMATION
    # ----------------------------------------

    for unit in units:

        log(
            f"ID: {unit['id']} | "
            f"Quality: {unit['quality_raw']} | "
            f"Impressions: {unit['impressions']} | "
            f"Clicks: {unit['clicks']} | "
            f"CTR: {unit['ctr']}"
        )

    # ----------------------------------------
    # FIND DELETE TARGETS
    # ----------------------------------------

    delete_targets = [

        unit for unit in units

        if unit["quality"] is not None

        and unit["quality"] < 80

        and unit["impressions"] is not None

        and unit["impressions"] > 30

    ]

    log(
        f"Ad units qualifying for deletion: {len(delete_targets)}"
    )

    deleted_any = False

    # ----------------------------------------
    # DELETE ALL QUALIFYING UNITS
    # ----------------------------------------

    for unit in delete_targets:

        identifier = unit["id"]

        if delete_ad_unit(page, identifier):

            deleted_any = True

    if deleted_any:

        log(
            "One or more ad units were successfully deleted."
        )

    else:

        log(
            "No ad units were successfully deleted."
        )

    # ----------------------------------------
    # MAIN REQUEST
    # RUN EVERY CYCLE
    # ----------------------------------------

    log(
        "Checking for ad units with quality >= 80%..."
    )

    # Refresh the list after deletion attempts.

    click_ad_units_tab(page)

    units = get_ad_units(page)

    qualified_units = [

        unit for unit in units

        if unit["quality"] is not None

        and unit["quality"] >= 80

    ]

    if qualified_units:

        # Select the LAST qualifying ad unit.

        selected = qualified_units[-1]

        identifier = selected["id"]

        log(
            f"Selected last qualifying ad unit: #{identifier}"
        )

        send_request(
            context,
            API_MAIN,
            identifier
        )

    else:

        log(
            "No ad unit with quality >= 60% found. Skipping MAIN request."
        )

    # ----------------------------------------
    # SECONDARY REQUEST CHECK
    # ----------------------------------------

    log(
        "Checking empty-quality units with impressions < 22..."
    )

    units = get_ad_units(page)

    secondary_targets = [

        unit for unit in units

        if unit["quality_empty"]

        and unit["impressions"] is not None

        and unit["impressions"] < 22

    ]

    # ----------------------------------------
    # SEND SEC REQUESTS
    # ----------------------------------------

    if secondary_targets:

        log(
            f"Found {len(secondary_targets)} secondary candidates."
        )

        for unit in secondary_targets:

            identifier = unit["id"]

            log(
                f"Sending SEC request for #{identifier}"
            )

            send_request(
                context,
                API_SEC,
                identifier
            )

        return

    # ----------------------------------------
    # CREATE NEW AD UNIT
    # ----------------------------------------

    log(
        "No qualifying secondary ad unit found."
    )

    existing_ids = {

        unit["id"] for unit in units

    }

    create_ad_unit(
        page,
        context,
        existing_ids
    )


# ============================================================
# MAIN AUTOMATION LOOP
# ============================================================

def main():

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=False
        )

        # ----------------------------------------
        # MOBILE VIEWPORT
        # ----------------------------------------

        context = browser.new_context(

            viewport={
                "width": MOBILE_WIDTH,
                "height": MOBILE_HEIGHT
            },

            device_scale_factor=3,

            is_mobile=True,

            has_touch=True

        )

        page = context.new_page()

        # ----------------------------------------
        # LOGIN
        # ----------------------------------------

        login(page)

        log("=" * 55)
        log("AUTOMATION STARTED")
        log(f"Monitoring interval: {CHECK_INTERVAL} seconds")
        log("=" * 55)

        next_cycle = None

        while True:

            try:

                # --------------------------------
                # WAIT FOR NEXT CYCLE
                # --------------------------------

                if next_cycle is not None:

                    remaining = max(
                        0,
                        next_cycle - time.monotonic()
                    )

                    if remaining > 0:

                        log(
                            f"Next check in {remaining:.1f} seconds."
                        )

                        time.sleep(remaining)

                    # Reload every two minutes.

                    log("Reloading Surfe...")

                    page.reload(
                        wait_until="domcontentloaded",
                        timeout=60000
                    )

                # --------------------------------
                # OPEN AD UNITS
                # --------------------------------

                click_ad_units_tab(page)

                cycle_start = time.monotonic()

                # --------------------------------
                # PROCESS
                # --------------------------------

                process_ad_units(
                    page,
                    context
                )

                log("")
                log("=" * 55)
                log("CHECK COMPLETED")
                log("=" * 55)

                next_cycle = (
                    cycle_start + CHECK_INTERVAL
                )

            except KeyboardInterrupt:

                log("Automation stopped.")

                break

            except Exception as error:

                log(
                    f"MAIN LOOP ERROR: {error}"
                )

                next_cycle = (
                    time.monotonic() + CHECK_INTERVAL
                )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        log("Automation terminated.")

    except Exception as error:

        log(
            f"FATAL ERROR: {error}"
        )
