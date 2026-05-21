import logging
import os
import json
import secrets
from threading import Thread
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, redirect, url_for

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters

# 📄 PDF IMPORTS
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# Configure Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

DATA_FILE = "data.json"
BOT_TOKEN = "8609637925:AAEAbSqyzXsFw1a_Ue0XlaXIVkr64xXswGU" # ⚠️ Make sure you replace this with a freshly revoked token!

# =========================
# INITIALIZE DATABASE STATE
# =========================
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
else:
    data = {
        "groups": {},         # Financial states & tx history per group
        "global_admins": [8155651577], # Superadmin Telegram ID
        "usernames": {},       # Map of user_id -> string username
        "whitelist": [],       # Whitelisted user IDs for transactions
        "limits": {},          # Financial limit markers
        "languages": {},       # Group language preferences
        "licenses": {},        # Active group licenses: { group_id: expiry_timestamp }
        "active_keys": {}      # Unused licenses available for redemption: { key: days_valid }
    }

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def init_group(group_id):
    group_id = str(group_id)
    if group_id not in data["groups"]:
        data["groups"][group_id] = {
            "users": {},
            "history": [],
            "admins": [],
            "tx_count": 0
        }

# =========================
# LICENSE SUBSCRIPTION MIDDLEWARE
# =========================
def check_group_license(group_id) -> bool:
    """Verifies if a group chat holds an active, unexpired commercial license."""
    group_id = str(group_id)
    
    # Global admin test channels or direct messages pass automatically
    if int(group_id) in data["global_admins"] or int(group_id) > 0: 
        return True
        
    if group_id not in data["licenses"]:
        return False
        
    expiry_date_str = data["licenses"][group_id]
    expiry_time = datetime.strptime(expiry_date_str, "%Y-%m-%d %H:%M:%S")
    
    if datetime.now() > expiry_time:
        return False # License expired
        
    return True

# =========================
# CORE BOT COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not check_group_license(group_id):
        await update.message.reply_text("❌ This group is not whitelisted or its license has expired.\nPlease use `/activate <your_key>` or contact the bot owner.")
        return
    await update.message.reply_text("🏦 Banking Bot Active & Licensed")

async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/activate YOUR_LICENSE_KEY`")
        return
        
    key = context.args[0].strip()
    
    if key in data.get("active_keys", {}):
        days = data["active_keys"][key]
        
        # Calculate lifespan extension
        new_expiry = datetime.now() + timedelta(days=days)
        data["licenses"][group_id] = new_expiry.strftime("%Y-%m-%d %H:%M:%S")
        
        # Consume key
        del data["active_keys"][key]
        init_group(group_id)
        save_data()
        
        await update.message.reply_text(f"💎 SUCCESS! Group activated.\n📅 Expiry Date: {data['licenses'][group_id]} ({days} Days)")
    else:
        await update.message.reply_text("❌ Invalid, used, or expired activation key.")

async def generate_key_tg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback generation via Telegram for the superadmin."""
    user_id = update.effective_user.id
    if user_id not in data["global_admins"]:
        return
        
    days = 30
    if context.args:
        try: days = int(context.args[0])
        except ValueError: pass
        
    new_key = f"PREM-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
    data["active_keys"][new_key] = days
    save_data()
    
    await update.message.reply_text(f"🔑 Key Generated: `{new_key}`\n⏱️ Duration: {days} Days")

# =========================
# ADMIN & STANDARD ACTIONS (LICENSE PROTECTED)
# =========================
def is_admin(group_id, user_id):
    if user_id in data["global_admins"]: return True
    g = data["groups"].get(str(group_id), {})
    return user_id in g.get("admins", [])

def is_whitelisted(user_id):
    return user_id in data["whitelist"] or user_id in data["global_admins"]

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not check_group_license(group_id): return

    user_id = update.effective_user.id
    init_group(group_id)

    try:
        member = await context.bot.get_chat_member(chat_id=update.effective_chat.id, user_id=user_id)
        if member.status in ['creator', 'administrator'] and user_id not in data["groups"][group_id]["admins"]:
            data["groups"][group_id]["admins"].append(user_id)
            save_data()
    except Exception: pass

    if not is_admin(group_id, user_id):
        await update.message.reply_text("🚫 No permission")
        return

    keyboard = [
        [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton("💰 Balances", callback_data="balances")],
        [InlineKeyboardButton("📜 History", callback_data="history")]
    ]
    await update.message.reply_text("👑 ADMIN PANEL", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    group_id = str(query.message.chat.id)
    if not check_group_license(group_id): return

    user_id = query.from_user.id
    await query.answer()
    
    if not is_admin(group_id, user_id): return

    g = data["groups"][group_id]
    if query.data == "dashboard":
        await query.message.reply_text(f"📊 Dashboard\nUsers: {len(g['users'])}\nTotal: {sum(g['users'].values())} TRY")
    elif query.data == "balances":
        text = "💰 BALANCES\n\n"
        for uid, bal in g["users"].items():
            text += f"👤 @{data['usernames'].get(str(uid), 'unknown')} → {bal} TRY\n"
        await query.message.reply_text(text)
    elif query.data == "history":
        await query.message.reply_text("📜 LAST 5:\n" + ("\n".join(g["history"][-5:]) or "No history"))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    group_id = str(update.effective_chat.id)
    if not check_group_license(group_id): return

    msg = update.message
    text = msg.text.strip().replace(" ", "")

    if not (text.startswith("+") or text.startswith("-")): return
    if not is_whitelisted(msg.from_user.id):
        await msg.reply_text("🚫 You are not whitelisted to adjust values.")
        return
    if not msg.reply_to_message: return

    target_user = msg.reply_to_message.from_user
    target_id = str(target_user.id)
    data["usernames"][target_id] = target_user.username or target_user.first_name

    try: amount = int(text)
    except ValueError: return

    g = data["groups"][group_id]
    current = g["users"].get(target_id, 0)
    
    # Check bounds limit execution
    limit = data["limits"].get(target_id)
    if limit is not None and current + amount > limit:
        await msg.reply_text("🚫 Limit exceeded!")
        return

    now = datetime.now().strftime("%H:%M:%S")
    g["users"][target_id] = current + amount
    g["history"].append(f"{now} | {target_id} | {amount}")
    g["tx_count"] = g.get("tx_count", 0) + 1
    
    save_data()
    await msg.reply_text(f"✅ Balance updated. User target: @{data['usernames'][target_id]} -> New Total: {g['users'][target_id]} TRY")

# =========================
# WEB DASHBOARD (FLASK APPARATUS)
# =========================
web_app = Flask(__name__)

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Owner Web Panel</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #e2e8f0; margin: 40px; }
        .card { background: #1e293b; padding: 24px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); margin-bottom: 24px; }
        h1, h2 { color: #38bdf8; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #334155; }
        th { background: #334155; color: #f8fafc; }
        .btn { background: #0284c7; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; text-decoration: none; font-weight: bold;}
        .btn:hover { background: #0369a1; }
        input[type="number"] { padding: 8px; border-radius: 4px; border: 1px solid #475569; background: #0f172a; color: white; width: 80px;}
    </style>
</head>
<body>
    <h1>💎 Bot Owner Licensing Matrix</h1>
    
    <div class="card">
        <h2>Generate Activation Key</h2>
        <form action="/web/generate" method="post">
            <label>Subscription Duration (Days): </label>
            <input type="number" name="days" value="30" min="1">
            <button type="submit" class="btn">Generate Key</button>
        </form>
    </div>

    <div class="card">
        <h2>Unused Activation Keys</h2>
        <table>
            <tr><th>License Key</th><th>Duration</th></tr>
            {% for key, days in active_keys.items() %}
            <tr><td><code>{{ key }}</code></td><td>{{ days }} Days</td></tr>
            {% endfor %}
        </table>
    </div>

    <div class="card">
        <h2>Licensed Active Groups</h2>
        <table>
            <tr><th>Group Chat ID</th><th>Expiration Timestamp</th></tr>
            {% for gid, exp in licenses.items() %}
            <tr><td>{{ gid }}</td><td>{{ exp }}</td></tr>
            {% endfor %}
        </table>
    </div>
</body>
</html>
"""

@web_app.route('/')
def home():
    return render_template_string(DASHBOARD_HTML, active_keys=data["active_keys"], licenses=data["licenses"])

@web_app.route('/web/generate', methods=['POST'])
def web_generate_key():
    days = int(request.form.get("days", 30))
    new_key = f"PREM-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
    data["active_keys"][new_key] = days
    save_data()
    return redirect(url_for('home'))

def run_web_server():
    # Listens on 0.0.0.0:8080 which maps natively to Replit's web viewing proxy
    web_app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

# =========================
# RUN BOT & SUBPROCESS ASYNC RUNNERS
# =========================
if __name__ == '__main__':
    # 1. Thread off the Web Interface server execution stack
    print("🌐 Launching Control Web App on Port 8080...")
    server_thread = Thread(target=run_web_server, daemon=True)
    server_thread.start()

    # 2. Fire up the Telegram application engine thread
    print("🚀 Booting Telegram Listening Core...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(CommandHandler("keygen", generate_key_tg))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ System Online and Synced via Replit runtime bindings.")
    app.run_polling()