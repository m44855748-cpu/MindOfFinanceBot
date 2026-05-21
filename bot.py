import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
from datetime import datetime, timedelta
import json
import os
import secrets
from threading import Thread
from flask import Flask, render_template_string, request, redirect, url_for

# 📄 PDF IMPORTS
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

DATA_FILE = "data.json"

# =========================
# LOAD DATA WITH LICENSE KEYS
# =========================
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
    # Ensure missing licensing structures are appended safely to existing json setups
    if "licenses" not in data:
        data["licenses"] = {}
    if "active_keys" not in data:
        data["active_keys"] = {}
else:
    data = {
        "groups": {},
        "global_admins": [8155651577],
        "usernames": {},
        "whitelist": [],
        "limits": {},
        "languages": {},
        "licenses": {},      # Format: { "group_id": "YYYY-MM-DD HH:MM:SS" }
        "active_keys": {}    # Format: { "KEY-STRING": days_integer }
    }

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def init_group(group_id):
    if group_id not in data["groups"]:
        data["groups"][group_id] = {
            "users": {},
            "history": [],
            "admins": [],
            "tx_count": 0
        }

# =========================
# 💎 LICENSE SYSTEM ENGINE
# =========================
def is_group_licensed(group_id: str) -> bool:
    """Checks if a group chat has a valid, active unexpired subscription."""
    # Direct Messages with the superadmin are unlocked by default
    if int(group_id) in data["global_admins"] or int(group_id) > 0:
        return True
    
    if group_id not in data["licenses"]:
        return False
        
    expiry_time_str = data["licenses"][group_id]
    try:
        expiry_time = datetime.strptime(expiry_time_str, "%Y-%m-%d %H:%M:%S")
        if datetime.now() > expiry_time:
            return False
        return True
    except ValueError:
        return False

# =========================
# LANGUAGE SYSTEM
# =========================
LANG = {
    "en": "TRANSACTION",
    "tr": "İŞLEM",
    "ar": "المعاملة",
    "ru": "ТРАНЗАКЦИЯ"
}

def get_lang(group_id):
    return data["languages"].get(group_id, "en")

async def set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id):
        await update.message.reply_text("❌ This group is not whitelisted or subscription expired. Run /activate <key>")
        return

    if not context.args:
        await update.message.reply_text("Usage: /lang en")
        return

    lang = context.args[0].lower()

    if lang not in LANG:
        await update.message.reply_text("Supported: en, tr, ar, ru")
        return

    data["languages"][group_id] = lang
    save_data()

    await update.message.reply_text(f"🌍 Language set to {lang}")

# =========================
# ADMIN CHECK
# =========================
def is_admin(group_id, user_id):
    g = data["groups"].get(group_id, {})
    return user_id in g.get("admins", []) or user_id in data["global_admins"]

def is_whitelisted(user_id):
    return user_id in data["whitelist"] or user_id in data["global_admins"]

# =========================
# 💎 TELEGRAM ACTIVATION COMMANDS
# =========================
async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/activate PREM-XXXX-XXXX`")
        return
        
    key = context.args[0].strip().upper()
    
    if key in data["active_keys"]:
        days = data["active_keys"][key]
        
        # Calculate new expiration window
        current_expiry = datetime.now()
        if group_id in data["licenses"]:
            try:
                parsed_expiry = datetime.strptime(data["licenses"][group_id], "%Y-%m-%d %H:%M:%S")
                if parsed_expiry > current_expiry:
                    current_expiry = parsed_expiry
            except ValueError:
                pass
                
        extended_expiry = current_expiry + timedelta(days=days)
        data["licenses"][group_id] = extended_expiry.strftime("%Y-%m-%d %H:%M:%S")
        
        # Consume key
        del data["active_keys"][key]
        init_group(group_id)
        save_data()
        
        await update.message.reply_text(f"💎 **Success! Group Activated**\n📅 Expiry Date: `{data['licenses'][group_id]}` (+{days} Days)")
    else:
        await update.message.reply_text("❌ Invalid, expired, or already used activation key.")

async def keygen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows Superadmins to generate license keys on the fly from Telegram."""
    user_id = update.effective_user.id
    if user_id not in data["global_admins"]:
        return
        
    days = 30
    if context.args:
        try:
            days = int(context.args[0])
        except ValueError:
            pass
            
    token_string = f"PREM-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
    data["active_keys"][token_string] = days
    save_data()
    
    await update.message.reply_text(f"🔑 **Generated Activation Key:**\n`{token_string}`\n⏱️ Duration: {days} days")

# =========================
# START
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id):
        await update.message.reply_text("❌ This group is not whitelisted or license expired. Activate using /activate <key>")
        return
    await update.message.reply_text("🏦 Banking Bot Active")

# =========================
# RESET
# =========================
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return
    
    user_id = update.effective_user.id

    init_group(group_id)

    if not is_admin(group_id, user_id):
        await update.message.reply_text("🚫 No permission")
        return

    data["groups"][group_id]["users"] = {}
    data["groups"][group_id]["history"] = []
    data["groups"][group_id]["tx_count"] = 0

    save_data()

    await update.message.reply_text("🔄 Balance reset completed")

# =========================
# WHITELIST
# =========================
async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return
    
    user_id = update.effective_user.id

    if user_id not in data["global_admins"]:
        await update.message.reply_text("🚫 Only superadmin")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user")
        return

    target_id = update.message.reply_to_message.from_user.id

    if target_id not in data["whitelist"]:
        data["whitelist"].append(target_id)
        save_data()

    await update.message.reply_text("✅ User whitelisted")

async def deny(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return
    
    user_id = update.effective_user.id

    if user_id not in data["global_admins"]:
        await update.message.reply_text("🚫 Only superadmin")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user")
        return

    target_id = update.message.reply_to_message.from_user.id

    if target_id in data["whitelist"]:
        data["whitelist"].remove(target_id)
        save_data()

    await update.message.reply_text("❌ Removed from whitelist")

async def show_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return
    
    if not data["whitelist"]:
        await update.message.reply_text("Whitelist empty")
        return

    text = "📋 WHITELIST:\n\n"

    for uid in data["whitelist"]:
        name = data["usernames"].get(str(uid), f"ID:{uid}")
        text += f"• @{name}\n"

    await update.message.reply_text(text)

# =========================
# LIMIT SYSTEM
# =========================
async def set_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return
    
    user_id = update.effective_user.id

    if user_id not in data["global_admins"]:
        await update.message.reply_text("🚫 Only superadmin")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to user")
        return

    if not context.args:
        await update.message.reply_text("Usage: /setlimit 1000")
        return

    target = update.message.reply_to_message.from_user
    target_id = str(target.id)

    limit_amount = int(context.args[0])

    data["limits"][target_id] = limit_amount
    save_data()

    await update.message.reply_text(f"✅ Limit set: {limit_amount}")

# =========================
# ADMIN PANEL
# =========================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return
    
    user_id = update.effective_user.id

    init_group(group_id)

    if not is_admin(group_id, user_id):
        await update.message.reply_text("🚫 No permission")
        return

    keyboard = [
        [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton("💰 Balances", callback_data="balances")],
        [InlineKeyboardButton("📜 History", callback_data="history")],
        [InlineKeyboardButton("🔄 Reset", callback_data="reset")]
    ]

    await update.message.reply_text(
        "👑 ADMIN PANEL",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =========================
# BUTTON HANDLER
# =========================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    group_id = str(query.message.chat.id)
    if not is_group_licensed(group_id): return
    
    init_group(group_id)
    g = data["groups"][group_id]

    total = sum(g["users"].values())

    if query.data == "dashboard":
        text = f"📊 Dashboard\nUsers: {len(g['users'])}\nTotal: {total} TRY"

    elif query.data == "balances":
        text = "💰 BALANCES\n\n"
        for uid, bal in g["users"].items():
            name = data["usernames"].get(uid, "unknown")
            text += f"👤 @{name} → {bal} TRY\n"

    elif query.data == "history":
        text = "\n".join(g["history"][-5:]) or "No history"

    elif query.data == "reset":
        g["users"] = {}
        g["history"] = []
        g["tx_count"] = 0
        save_data()
        text = "🔄 Reset done"

    else:
        text = "Unknown"

    await query.message.reply_text(text)

# =========================
# 📄 PDF EXPORT (FIXED TX COUNT)
# =========================
def generate_pdf(group_id, g):
    filename = f"{group_id}_statement.pdf"
    c = canvas.Canvas(filename, pagesize=A4)

    y = 800

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "TRANSACTION STATEMENT")
    y -= 30

    tx = g.get("tx_count", 0)  # ✅ FIXED HERE

    for item in g["history"][-50:]:

        parts = item.split(" | ")
        if len(parts) == 3:
            time, uid, amount = parts
            name = data["usernames"].get(uid, uid)

            line = f"{tx}. @{name} | {amount} TRY | {time}"
            c.drawString(50, y, line)

            y -= 15
            tx -= 1

            if y < 50:
                c.showPage()
                y = 800

    c.save()
    return filename

async def pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return
    
    init_group(group_id)
    g = data["groups"][group_id]

    file = generate_pdf(group_id, g)

    await update.message.reply_document(document=open(file, "rb"))

    os.remove(file)

# ==================================
# MAIN SYSTEM (ORIGINAL CONFIGURATION)
# ==================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    msg = update.message
    text = msg.text.strip()

    group_id = str(update.effective_chat.id)
    
    # Check if group whitelist license parameters are valid
    if not is_group_licensed(group_id):
        return

    user_id = msg.from_user.id

    init_group(group_id)
    g = data["groups"][group_id]

    if not is_whitelisted(user_id):
        await msg.reply_text("🚫 You are not whitelisted")
        return

    if not msg.reply_to_message:
        return

    target_user = msg.reply_to_message.from_user
    target_id = str(target_user.id)

    # Protection framework against bot target logic mutations
    if target_user.is_bot:
        return

    username = target_user.username or target_user.first_name
    data["usernames"][target_id] = username

    if not (text.startswith("+") or text.startswith("-")):
        return

    try:
        amount = int(text)
    except:
        await msg.reply_text("❌ Use +100 / -50")
        return

    current = g["users"].get(target_id, 0)
    limit = data["limits"].get(target_id)

    if limit is not None and current + amount > limit:
        await msg.reply_text("🚫 Limit exceeded!")
        return

    now = datetime.now().strftime("%H:%M:%S")

    g["users"][target_id] = current + amount
    g["history"].append(f"{now} | {target_id} | {amount}")

    if len(g["history"]) > 100:
        g["history"].pop(0)

    # =========================
    # ✅ FIXED TRANSACTION NUMBER
    # =========================
    g["tx_count"] = g.get("tx_count", 0) + 1
    tx_number = g["tx_count"]

    save_data()

    total = sum(g["users"].values())
    fee = int(total * 0.10)

    members = "\n".join(
        [f"👤 @{data['usernames'].get(uid,'unknown')} → {bal} TRY"
         for uid, bal in g["users"].items()]
    )

    lang = get_lang(group_id)
    title = LANG.get(lang, "TRANSACTION")

    reply = f"""
━━━━━━━━━━━━━━
TRANSACTION #{tx_number}
━━━━━━━━━━━━━━
{title}
━━━━━━━━━━━━━━

{members}

💰 Amount: {amount} TRY
⏰ Time: {now}

📊 Total: {total} TRY
💸 Fee: {fee}
━━━━━━━━━━━━━━
"""

    await msg.reply_text(reply)

# =====================================
# 💎 OWNER DASHBOARD (FLASK APPARATUS)
# =====================================
web_app = Flask(__name__)

OWNER_DASHBOARD_UI = """
<!DOCTYPE html>
<html>
<head>
    <title>Owner Control Center</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0f19; color: #f1f5f9; padding: 40px; margin: 0; }
        .wrapper { max-width: 1100px; margin: 0 auto; }
        .block { background: #131c2e; padding: 25px; border-radius: 10px; margin-bottom: 25px; border: 1px solid #1e293b; }
        h1, h2 { margin-top: 0; color: #38bdf8; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #1e293b; }
        th { background: #1e293b; color: #94a3b8; }
        .btn { background: #0284c7; color: white; border: none; padding: 10px 20px; font-weight: bold; border-radius: 5px; cursor: pointer; text-decoration: none; }
        .btn:hover { background: #0369a1; }
        input[type="number"] { background: #0b0f19; border: 1px solid #334155; padding: 8px; border-radius: 4px; color: white; width: 100px; }
    </style>
</head>
<body>
    <div class="wrapper">
        <h1>💎 Owner Subscription Management Console</h1>
        
        <div class="block">
            <h2>Generate Group License Key</h2>
            <form action="/owner/generate" method="post">
                <label>Lifespan Duration (Days): </label>
                <input type="number" name="days" value="30" min="1">
                <button type="submit" class="btn">Mint License Key</button>
            </form>
        </div>

        <div class="block">
            <h2>Unused Keys Available for Purchase</h2>
            <table>
                <tr><th>Activation Serial Key</th><th>Valid Duration</th></tr>
                {% for key, days in active_keys.items() %}
                <tr><td><code>{{ key }}</code></td><td>{{ days }} Days</td></tr>
                {% endfor %}
            </table>
        </div>

        <div class="block">
            <h2>Currently Whitelisted/Activated Telegram Groups</h2>
            <table>
                <tr><th>Group Identifier Chat ID</th><th>Expiration Timestamp</th></tr>
                {% for gid, exp in licenses.items() %}
                <tr><td>{{ gid }}</td><td>{{ exp }}</td></tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
"""

@web_app.route('/')
def home():
    return render_template_string(OWNER_DASHBOARD_UI, active_keys=data["active_keys"], licenses=data["licenses"])

@web_app.route('/owner/generate', methods=['POST'])
def generate_key_web():
    days = int(request.form.get("days", 30))
    token_string = f"PREM-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
    data["active_keys"][token_string] = days
    save_data()
    return redirect(url_for('home'))

def run_flask_panel():
    # Bind to 0.0.0.0:8080 to accommodate Replit live port forwarding architecture
    web_app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

# =========================
# RUN BOT
# =========================
if __name__ == '__main__':
    print("🚀 Initializing Operational Background Threads...")
    
    # 1. Start the Flask Control Panel asynchronous thread
    web_worker = Thread(target=run_flask_panel, daemon=True)
    web_worker.start()

    # 2. Boot the main polling pipeline for Telegram
    print("🚀 Bot starting...")
    
    # Ensure you load your custom key inside the token string wrapper safely
    app = ApplicationBuilder().token("8609637925:AAFghPrdrlwwKiR41IPxp8mIlYsCqDb-wCE").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(CommandHandler("keygen", keygen))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("reset", reset))

    app.add_handler(CommandHandler("allow", allow))
    app.add_handler(CommandHandler("deny", deny))
    app.add_handler(CommandHandler("whitelist", show_whitelist))
    app.add_handler(CommandHandler("setlimit", set_limit))

    app.add_handler(CommandHandler("lang", set_lang))
    app.add_handler(CommandHandler("pdf", pdf))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("✅ Bot running...")
    app.run_polling()
