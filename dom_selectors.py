"""
QVC Appointment Booking Bot - DOM Selectors

Exact selectors extracted from live qatarvisacenter.com DOM.
Site is Angular 10.2.4 with custom sb-datepicker component.

Last verified: 2026-03-24
"""


# =============================================================================
# CALENDAR PAGE DETECTION
# Detects when user has completed login and reached the appointment calendar
# =============================================================================
CALENDAR_CONTAINER = [
    "sb-datepicker",                        # The custom datepicker component
    ".datepicker__wrapper",                 # Inner wrapper
    ".datepicker__calendar",                # Calendar table
]

# =============================================================================
# CALENDAR NAVIGATION
# =============================================================================
NEXT_MONTH_BUTTON = [
    "button.navigation__button.is-next",    # Exact match from DOM
]

PREV_MONTH_BUTTON = [
    "button.navigation__button.is-previous",  # Exact match from DOM
]

MONTH_YEAR_LABEL = [
    ".navigation__title",                   # Contains <span>Month</span> <span>Year</span>
]

# =============================================================================
# DATE CELLS
# Available = NOT disabled, NOT hidden, NOT a rest day
# The site adds 'is-disabled' class + disabled attribute on button when no slots
# When a slot opens, the td loses 'is-disabled' and button loses 'disabled'
# =============================================================================
AVAILABLE_DATE = [
    "td.datepicker__day:not(.is-disabled):not(.is-hidden):not(.is-rest) button.datepicker__button:not([disabled])",
]

UNAVAILABLE_DATE = [
    "td.datepicker__day.is-disabled",       # Disabled date cells
]

# =============================================================================
# TIME SLOTS
# Shows after clicking an available date
# Currently shows "No slots available for the selected date" div
# =============================================================================
TIME_SLOT_LIST = [
    ".schedule-list .row",                  # Row container for time slots
    "qvc-slotdetails .row",                 # Broader container
]

TIME_SLOT_ITEM = [
    # Time slots appear as radio buttons or clickable items after date selection
    "input[type='radio'][name*='time']",    # Radio button slots
    ".slot-item:not(.disabled)",            # Slot items
    ".time-slot:not(.disabled)",            # Time slot class
    "button.slot-btn:not([disabled])",      # Button-based slots
]

# =============================================================================
# PROCEED / SUBMIT BUTTONS
# =============================================================================
PROCEED_BUTTON = [
    # The "Next" button in the calendar page (2nd button, after "Back")
    "qvc-slotdetails button.cir-em-btn:not([disabled]):last-of-type",
    "button.cir-em-btn:not([disabled]):nth-child(2)",
    # Broader fallbacks
    "button.btn.cir-em-btn:not([disabled])",
]

BACK_BUTTON = [
    "qvc-slotdetails button.cir-em-btn:first-of-type",
]

# =============================================================================
# CAPTCHA #2
# These appear after clicking Next on the time slot page
# =============================================================================
CAPTCHA_IMAGE = [
    "#imgCaptcha",
    "img[src*='captcha']",
    "img[src*='Captcha']",
    ".captcha-image img",
    "#CaptchaImage",
    "img[alt*='captcha']",
    "img[alt*='Captcha']",
]

CAPTCHA_INPUT = [
    "#txtCaptcha",
    "input[name*='captcha']",
    "input[name*='Captcha']",
    "input[placeholder*='captcha']",
    "input[placeholder*='code']",
    "input[placeholder*='Code']",
    "#CaptchaInputText",
]

SUBMIT_BUTTON = [
    "#btnSubmit",
    "input[type='submit'][value*='Submit']",
    "button:has-text('Submit')",
    "button:has-text('Confirm')",
    "input[type='submit'][value*='Confirm']",
    ".btn-submit",
    "#btnConfirm",
]

# =============================================================================
# ERROR / NOTIFICATION MODALS
# The site has several modal IDs for different error types
# All use <modal> custom element with style="display: none|block"
# =============================================================================
ERROR_MODAL = [
    # Session expired modal (most critical)
    "modal#modalSessionExpired .modal[style*='display: block']",
    "modal#modalSessionExpired .modal[style*='display:block']",
    # Generic website alert
    "modal#webSiteAlert .modal[style*='display: block']",
    "modal#webSiteAlert .modal[style*='display:block']",
    # Service not available
    "modal#modalServiceNotAvail .modal[style*='display: block']",
    "modal#modalServiceNotAvail .modal[style*='display:block']",
    # Unauthorized
    "modal#modalUnAuthorised .modal[style*='display: block']",
    "modal#modalUnAuthorised .modal[style*='display:block']",
    # Slot notification
    "modal#slotNotification .modal[style*='display: block']",
    "modal#slotNotification .modal[style*='display:block']",
    # Slot available check
    "modal#slotAvailableCheck .modal[style*='display: block']",
    "modal#slotAvailableCheck .modal[style*='display:block']",
    # Active session warning
    "modal .modal[style*='display: block']:has-text('active session')",
    # Connection lost
    "modal .modal[style*='display: block']:has-text('Connection')",
    "modal .modal[style*='display: block']:has-text('server is lost')",
    # Catch-all: any visible modal
    "modal .modal[style*='display: block']",
    "modal .modal[style*='display:block']",
]

ERROR_DISMISS_BUTTON = [
    # Modal OK/Close buttons
    "modal .modal[style*='display: block'] button",
    "modal .modal[style*='display:block'] button",
    "modal .modal-dialog button.btn",
    ".modal.show button.btn",
    "button:has-text('OK')",
    "button:has-text('Close')",
]

# =============================================================================
# CONFIRMATION PAGE
# Appears after successful CAPTCHA submission
# =============================================================================
CONFIRMATION_ELEMENT = [
    ".confirmation",
    ".booking-confirmed",
    ".success-message",
    ".alert-success",
    # Progress bar step 3 active (the site has 3 steps in the right panel)
    ".applicant-progress-bar li:nth-child(3).active",
    "h2:has-text('Confirmed')",
    "h1:has-text('Booking Confirmed')",
]

# =============================================================================
# VCS CENTER DROPDOWN (for reference / future use)
# =============================================================================
VSC_DROPDOWN = [
    "button[name='selectedVsc']",           # The VCS center dropdown button
]

VSC_OPTIONS = [
    ".dropdown-menu li a",                  # Islamabad, Karachi options
]

# =============================================================================
# APPOINTMENT TYPE
# =============================================================================
APPOINTMENT_TYPE_NORMAL = [
    "input[type='radio'][name='appointmentType'][value='Normal']",
]
