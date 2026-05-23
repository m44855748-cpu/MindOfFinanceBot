import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
from datetime import datetime, timedelta, timezone
import json
import os
import secrets
from threading import Thread
from flask import Flask, render_template_string, request, redirect, url_for

# 📄 PDF IMPORTS
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

DATA_FILE = "data.json"

# =====================================================================
# 🌍 TIMEZONE ADJUSTMENT CONFIGURATION
# =====================================================================
LOCAL_TIMEZONE = timezone(timedelta(hours=3)) 

# =========================
# LOAD DATA WITH LICENSE KEYS
# =========================
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
    if "licenses" not in data:
        data["licenses"] = {}
    if "active_keys" not in data:
        data["active_keys"] = {}
    if "fees" not in data: 
        data["fees"] = {}
    if "agent_fees" not in data:
        data["agent_fees"] = {}
else:
    data = {
        "groups": {},
        "global_admins": [8155651577],
        "usernames": {},
        "whitelist": [],     
        "limits": {},
        "languages": {},
        "licenses": {},      
        "active_keys": {},
        "fees": {},
        "agent_fees": {}
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
    if "admins" not in data["groups"][group_id]:
        data["groups"][group_id]["admins"] = []

# =========================
# 💎 LICENSE SYSTEM ENGINE
# =========================
def is_group_licensed(group_id: str) -> bool:
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
    "en": {
        "title":     "TRANSACTION",
        "amount":    "Amount",
        "time":      "Time",
        "tx_fee":    "Tx Fee",
        "total":     "Total",
        "agent_fee": "Agent Fee",
    },
    "tr": {
        "title":     "İŞLEM",
        "amount":    "Miktar",
        "time":      "Zaman",
        "tx_fee":    "İşlem Ücreti",
        "total":     "Toplam",
        "agent_fee": "Acente Ücreti",
    },
    "ar": {
        "title":     "المعاملة",
        "amount":    "المبلغ",
        "time":      "الوقت",
        "tx_fee":    "رسوم المعاملة",
        "total":     "الإجمالي",
        "agent_fee": "رسوم الوكيل",
    },
    "ru": {
        "title":     "ТРАНЗАКЦИЯ",
        "amount":    "Сумма",
        "time":      "Время",
        "tx_fee":    "Комиссия",
        "total":     "Итого",
        "agent_fee": "Агентское вознаграждение",
    },
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

# =====================================================================
# 🔑 SECURITY HELPER FUNCTIONS
# =====================================================================
async def check_if_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    if user_id in data["global_admins"]:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=update.effective_chat.id, user_id=user_id)
        if member.status in ['creator', 'administrator']:
            return True
    except Exception:
        pass
    return False

def is_user_authorized(group_id: str, user_id: int) -> bool:
    if user_id in data["global_admins"] or user_id in data["whitelist"]:
        return True
    g = data["groups"].get(group_id, {})
    if user_id in g.get("admins", []):
        return True
    return False

# =====================================================================
# ⚙️ FLEXIBLE FEE SYSTEM CONFIGURATION
# =====================================================================
async def set_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return

    user_id = update.effective_user.id
    if not await check_if_admin(update, context, user_id):
        await update.message.reply_text("🚫 No permission. Only group administrators can adjust the fee rate.")
        return

    if not context.args:
        current_rate = data["fees"].get(group_id, 10)
        await update.message.reply_text(f"📊 Current fee rate for this group is {current_rate}%.\nUsage: `/setfee 15` to set it to 15%.")
        return

    try:
        new_rate = int(context.args[0])
        if new_rate < 0 or new_rate > 100:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid percentage number between 0 and 100.")
        return

    data["fees"][group_id] = new_rate
    save_data()
    await update.message.reply_text(f"✅ Group transaction fee rate has been updated to {new_rate}%.")

async def set_agent_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return

    user_id = update.effective_user.id
    if not await check_if_admin(update, context, user_id):
        await update.message.reply_text("🚫 No permission. Only group administrators can adjust the agent fee rate.")
        return

    if not context.args:
        current_rate = data["agent_fees"].get(group_id, 0)
        await update.message.reply_text(f"🤝 Current agent fee rate for this group is {current_rate}%.\nUsage: `/setagentfee 10` to set it to 10%.", parse_mode="Markdown")
        return

    try:
        new_rate = int(context.args[0])
        if new_rate < 0 or new_rate > 100:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid percentage number between 0 and 100.")
        return

    data["agent_fees"][group_id] = new_rate
    save_data()
    await update.message.reply_text(f"✅ Agent fee rate has been updated to {new_rate}%.")

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

        del data["active_keys"][key]
        init_group(group_id)
        save_data()

        await update.message.reply_text(f"💎 **Success! Group Activated**\n📅 Expiry Date: `{data['licenses'][group_id]}` (+{days} Days)")
    else:
        await update.message.reply_text("❌ Invalid, expired, or already used activation key.")

async def keygen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in data["global_admins"]:
        return

    days = 30
    if context.args:
        try: days = int(context.args[0])
        except ValueError: pass

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
    await update.message.reply_text("💹 MFinance Bot Active")

# =========================
# 🔄 LOCAL RESET 
# =========================
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return

    user_id = update.effective_user.id
    init_group(group_id)

    if not await check_if_admin(update, context, user_id):
        await update.message.reply_text("🚫 No permission. Only group administrators can reset balances.")
        return

    data["groups"][group_id]["users"] = {}
    data["groups"][group_id]["history"] = []
    data["groups"][group_id]["tx_count"] = 0
    save_data()

    await update.message.reply_text("🔄 Local balance database reset completed successfully.")

# =====================================================================
# 📋 LOCAL GROUP WHITELIST 
# =====================================================================
async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return

    user_id = update.effective_user.id
    init_group(group_id)

    if not await check_if_admin(update, context, user_id):
        await update.message.reply_text("🚫 Only group administrators can whitelist users here.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Reply to the user you want to whitelist.")
        return

    target = update.message.reply_to_message.from_user
    target_id = target.id

    if target.is_bot:
        await update.message.reply_text("❌ You cannot whitelist a bot.")
        return

    if target_id not in data["groups"][group_id]["admins"]:
        data["groups"][group_id]["admins"].append(target_id)
        data["usernames"][str(target_id)] = target.username or target.first_name
        save_data()

    await update.message.reply_text(f"✅ @{data['usernames'][str(target_id)]} is now whitelisted to adjust values in this group.")

async def deny(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return

    user_id = update.effective_user.id
    init_group(group_id)

    if not await check_if_admin(update, context, user_id):
        await update.message.reply_text("🚫 Only group administrators can remove users here.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Reply to the user you want to remove.")
        return

    target_id = update.message.reply_to_message.from_user.id

    if target_id in data["groups"][group_id]["admins"]:
        data["groups"][group_id]["admins"].remove(target_id)
        save_data()

    await update.message.reply_text("❌ User removed from this group's whitelist.")

async def show_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return
    init_group(group_id)

    local_admins = data["groups"][group_id]["admins"]
    if not local_admins and not data["whitelist"]:
        await update.message.reply_text("The group whitelist is currently empty.")
        return

    text = "📋 WHITELIST:\n\n"
    for uid in data["global_admins"]:
        text += f"👑 @{data['usernames'].get(str(uid), 'Superadmin')} (Global Master)\n"

    for uid in local_admins:
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

    if not await check_if_admin(update, context, user_id):
        await update.message.reply_text("🚫 No permission. Admins only.")
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

    if not await check_if_admin(update, context, user_id):
        await update.message.reply_text("🚫 No permission.")
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

    user_id = query.from_user.id
    init_group(group_id)
    g = data["groups"][group_id]

    if not await check_if_admin(query, context, user_id):
        return

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
# 📄 PDF EXPORT
# =========================
def generate_pdf(group_id, g):
    filename = f"{group_id}_statement.pdf"
    canvas_obj = canvas.Canvas(filename, pagesize=A4)
    y = 800

    canvas_obj.setFont("Helvetica-Bold", 14)
    canvas_obj.drawString(50, y, "TRANSACTION STATEMENT")
    y -= 30

    tx = g.get("tx_count", 0)  

    for item in g["history"][-50:]:
        parts = item.split(" | ")
        if len(parts) == 3:
            time, uid, amount = parts
            name = data["usernames"].get(uid, uid)
            line = f"{tx}. @{name} | {amount} TRY | {time}"
            canvas_obj.drawString(50, y, line)
            y -= 15
            tx -= 1
            if y < 50:
                canvas_obj.showPage()
                y = 800

    canvas_obj.save()
    return filename

async def pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id): return

    user_id = update.effective_user.id
    if not await check_if_admin(update, context, user_id):
        return

    init_group(group_id)
    g = data["groups"][group_id]

    file = generate_pdf(group_id, g)
    await update.message.reply_document(document=open(file, "rb"))
    os.remove(file)

# ==================================
# MAIN SYSTEM (BALANCED LOOP)
# ==================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return

    msg = update.message
    text = msg.text.strip()
    group_id = str(update.effective_chat.id)

    if not is_group_licensed(group_id): return

    user_id = msg.from_user.id
    init_group(group_id)
    g = data["groups"][group_id]

    # Silently ignore messages that aren't transaction attempts
    if not (text.startswith("+") or text.startswith("-")): return
    if not msg.reply_to_message: return

    target_user = msg.reply_to_message.from_user
    target_id = str(target_user.id)

    if target_user.is_bot: return

    # Only now check authorization — user is clearly trying a transaction
    if not is_user_authorized(group_id, user_id):
        if not await check_if_admin(update, context, user_id):
            await msg.reply_text("🚫 You must be an authorized administrator or whitelisted to adjust values.")
            return

    username = target_user.username or target_user.first_name
    data["usernames"][target_id] = username

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

    now = datetime.now(LOCAL_TIMEZONE).strftime("%H:%M:%S")

    g["users"][target_id] = current + amount
    g["history"].append(f"{now} | {target_id} | {amount}")

    if len(g["history"]) > 100:
        g["history"].pop(0)

    g["tx_count"] = g.get("tx_count", 0) + 1
    tx_number = g["tx_count"]

    save_data()

    total = sum(g["users"].values())

    # ⚙️ FLEXIBLE FEE CALCULATION
    fee_rate = data["fees"].get(group_id, 10)
    tx_fee = tx_number * fee_rate
    agent_fee_rate = data["agent_fees"].get(group_id, 0)
    agent_fee = int(total * (agent_fee_rate / 100.0))

    members = "\n".join(
        [f"👤 @{data['usernames'].get(uid,'unknown')} → {bal} TRY"
         for uid, bal in g["users"].items()]
    )

    lang = get_lang(group_id)
    L = LANG.get(lang, LANG["en"])

    reply = f"""
━━━━━━━━━━━━━━
{L['title']} #{tx_number}
━━━━━━━━━━━━━━

{members}

💰 {L['amount']}: {amount} TRY
⏰ {L['time']}: {now}
📈 {L['tx_fee']} (#{tx_number} × {fee_rate}): {tx_fee} TRY

📊 {L['total']}: {total} TRY
🤝 {L['agent_fee']} ({agent_fee_rate}%): {agent_fee} TRY
💼 Agent's Total Fee: {agent_fee + tx_fee} TRY
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

# =========================
# 📊 STATS COMMAND
# =========================
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in data["global_admins"]:
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    total_groups = len(data["groups"])
    total_users = sum(len(g.get("users", {})) for g in data["groups"].values())
    total_transactions = sum(g.get("tx_count", 0) for g in data["groups"].values())
    total_history = sum(len(g.get("history", [])) for g in data["groups"].values())

    now = datetime.now()
    active_licenses = 0
    expired_licenses = 0
    for gid, expiry_str in data["licenses"].items():
        try:
            expiry = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
            if expiry > now:
                active_licenses += 1
            else:
                expired_licenses += 1
        except ValueError:
            pass

    unused_keys = len(data.get("active_keys", {}))

    top_groups = sorted(
        data["groups"].items(),
        key=lambda x: x[1].get("tx_count", 0),
        reverse=True
    )[:5]

    top_lines = ""
    for i, (gid, gdata) in enumerate(top_groups, 1):
        tx = gdata.get("tx_count", 0)
        users = len(gdata.get("users", {}))
        top_lines += f"  {i}. Group `{gid}` — {tx} txs, {users} users\n"

    msg = (
        f"📊 *Bot Statistics*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👥 *Total Groups:* `{total_groups}`\n"
        f"👤 *Total Users:* `{total_users}`\n"
        f"💸 *Total Transactions:* `{total_transactions}`\n"
        f"📜 *History Entries:* `{total_history}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Active Licenses:* `{active_licenses}`\n"
        f"❌ *Expired Licenses:* `{expired_licenses}`\n"
        f"🔑 *Unused Keys:* `{unused_keys}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 *Top Groups by Transactions:*\n{top_lines if top_lines else '  No data yet.'}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

# =========================
# 📢 BROADCAST COMMAND
# =========================
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in data["global_admins"]:
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ Usage: `/broadcast Your message here`\n"
            "Sends your message to all groups that have ever been active.",
            parse_mode="Markdown"
        )
        return

    message_text = " ".join(context.args)
    group_ids = list(data["groups"].keys())

    sent = 0
    failed = 0
    for gid in group_ids:
        try:
            await context.bot.send_message(
                chat_id=int(gid),
                text=f"📢 *Announcement*\n\n{message_text}",
                parse_mode="Markdown"
            )
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"📢 *Broadcast complete!*\n✅ Delivered: `{sent}` groups\n❌ Failed: `{failed}` groups",
        parse_mode="Markdown"
    )

# =========================
# 🚫 REVOKE COMMAND
# =========================
async def revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in data["global_admins"]:
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ Usage: `/revoke <group_id>`\n"
            "Immediately deactivates a group's license.\n\n"
            "Use `/stats` to find group IDs.",
            parse_mode="Markdown"
        )
        return

    group_id = context.args[0].strip()

    if group_id not in data["licenses"]:
        await update.message.reply_text(f"❌ No active license found for group `{group_id}`.", parse_mode="Markdown")
        return

    old_expiry = data["licenses"].pop(group_id)
    save_data()

    await update.message.reply_text(
        f"🚫 *License Revoked*\n"
        f"Group: `{group_id}`\n"
        f"Was valid until: `{old_expiry}`\n\n"
        f"The group can no longer use the bot until re-activated.",
        parse_mode="Markdown"
    )

    try:
        await context.bot.send_message(
            chat_id=int(group_id),
            text="⛔ Your bot license has been revoked by the administrator. Please contact support to reactivate."
        )
    except Exception:
        pass

# =========================
# 📋 LISTGROUPS COMMAND
# =========================
async def listgroups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in data["global_admins"]:
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    if not data["groups"]:
        await update.message.reply_text("📋 No groups registered yet.")
        return

    now = datetime.now()
    lines = []

    for gid, gdata in data["groups"].items():
        tx = gdata.get("tx_count", 0)
        users = len(gdata.get("users", {}))

        if gid in data["licenses"]:
            try:
                expiry = datetime.strptime(data["licenses"][gid], "%Y-%m-%d %H:%M:%S")
                days_left = (expiry - now).days
                if days_left > 0:
                    status = f"✅ {days_left}d left"
                else:
                    status = "❌ Expired"
            except ValueError:
                status = "⚠️ Unknown"
        else:
            status = "🔓 No license"

        lines.append(f"`{gid}`\n  {status} | 💸 {tx} txs | 👤 {users} users")

    msg = "📋 *All Registered Groups*\n━━━━━━━━━━━━━━━━━━━\n" + "\n\n".join(lines)

    if len(msg) > 4000:
        chunks = []
        current = "📋 *All Registered Groups*\n━━━━━━━━━━━━━━━━━━━\n"
        for line in lines:
            if len(current) + len(line) > 4000:
                chunks.append(current)
                current = ""
            current += line + "\n\n"
        if current:
            chunks.append(current)
        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, parse_mode="Markdown")

# =========================
# ➕ EXTENDLICENSE COMMAND
# =========================
async def extendlicense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in data["global_admins"]:
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Usage: `/extendlicense <group_id> <days>`\n"
            "Adds days to a group's existing license.\n\n"
            "Example: `/extendlicense -1234567890 30`\n"
            "Use `/listgroups` to find group IDs.",
            parse_mode="Markdown"
        )
        return

    group_id = context.args[0].strip()
    try:
        days = int(context.args[1])
        if days <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Days must be a positive number.")
        return

    now = datetime.now()
    if group_id in data["licenses"]:
        try:
            current_expiry = datetime.strptime(data["licenses"][group_id], "%Y-%m-%d %H:%M:%S")
            if current_expiry < now:
                current_expiry = now
        except ValueError:
            current_expiry = now
    else:
        current_expiry = now

    new_expiry = current_expiry + timedelta(days=days)
    data["licenses"][group_id] = new_expiry.strftime("%Y-%m-%d %H:%M:%S")
    save_data()

    await update.message.reply_text(
        f"✅ *License Extended*\n"
        f"Group: `{group_id}`\n"
        f"➕ Added: `{days}` days\n"
        f"📅 New expiry: `{data['licenses'][group_id]}`",
        parse_mode="Markdown"
    )

    try:
        await context.bot.send_message(
            chat_id=int(group_id),
            text=f"🎉 Your MFinance Bot license has been extended by {days} days!\n📅 New expiry: {data['licenses'][group_id]}"
        )
    except Exception:
        pass

# =========================
# 🔍 USERINFO COMMAND
# =========================
async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in data["global_admins"]:
        await update.message.reply_text("❌ This command is for the bot owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ Usage: `/userinfo <user_id>`\n"
            "Shows a user's balance and activity across all groups.",
            parse_mode="Markdown"
        )
        return

    target_id = context.args[0].strip()
    username = data["usernames"].get(target_id, "unknown")

    found_groups = []
    for gid, gdata in data["groups"].items():
        if target_id in gdata.get("users", {}):
            balance = gdata["users"][target_id]
            user_txs = [e for e in gdata.get("history", []) if f"| {target_id} |" in e]
            found_groups.append((gid, balance, len(user_txs)))

    if not found_groups:
        await update.message.reply_text(f"❌ No data found for user `{target_id}`.", parse_mode="Markdown")
        return

    lines = ""
    for gid, balance, tx_count in found_groups:
        lines += f"  • Group `{gid}`\n    Balance: {balance} TRY | Txs: {tx_count}\n"

    msg = (
        f"🔍 *User Info*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 User ID: `{target_id}`\n"
        f"🔖 Username: @{username}\n"
        f"📦 Active in {len(found_groups)} group(s)\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{lines}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# =========================
# 🔄 RESETUSER COMMAND
# =========================
async def resetuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id):
        await update.message.reply_text("❌ This group is not licensed.")
        return

    user_id = update.effective_user.id
    if not await check_if_admin(update, context, user_id):
        await update.message.reply_text("🚫 No permission. Only group administrators can reset a user.")
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ Usage: `/resetuser <user_id>`\n"
            "Resets a specific user's balance to 0 in this group.",
            parse_mode="Markdown"
        )
        return

    target_id = context.args[0].strip()
    g = data["groups"].get(group_id, {})

    if target_id not in g.get("users", {}):
        await update.message.reply_text(f"❌ User `{target_id}` not found in this group.", parse_mode="Markdown")
        return

    old_balance = g["users"][target_id]
    g["users"][target_id] = 0
    username = data["usernames"].get(target_id, target_id)
    save_data()

    await update.message.reply_text(
        f"🔄 *User Balance Reset*\n"
        f"👤 User: @{username} (`{target_id}`)\n"
        f"💰 Previous balance: `{old_balance} TRY`\n"
        f"✅ New balance: `0 TRY`",
        parse_mode="Markdown"
    )

# =========================
# 💰 SETBALANCE COMMAND
# =========================
async def setbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id):
        await update.message.reply_text("❌ This group is not licensed.")
        return

    user_id = update.effective_user.id
    if not await check_if_admin(update, context, user_id):
        await update.message.reply_text("🚫 No permission. Only group administrators can set a user's balance.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Usage: `/setbalance <user_id> <amount>`\n"
            "Sets a user's balance to an exact amount.\n\n"
            "Example: `/setbalance 8458383548 500`",
            parse_mode="Markdown"
        )
        return

    target_id = context.args[0].strip()
    try:
        new_balance = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Amount must be a whole number.")
        return

    init_group(group_id)
    g = data["groups"][group_id]

    old_balance = g["users"].get(target_id, 0)
    g["users"][target_id] = new_balance
    username = data["usernames"].get(target_id, target_id)
    save_data()

    await update.message.reply_text(
        f"💰 *Balance Updated*\n"
        f"👤 User: @{username} (`{target_id}`)\n"
        f"📉 Previous: `{old_balance} TRY`\n"
        f"📈 New balance: `{new_balance} TRY`",
        parse_mode="Markdown"
    )

# =========================
# 📋 SUMMARY COMMAND
# =========================
async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = str(update.effective_chat.id)
    if not is_group_licensed(group_id):
        await update.message.reply_text("❌ This group is not licensed.")
        return

    user_id = update.effective_user.id
    if not await check_if_admin(update, context, user_id):
        await update.message.reply_text("🚫 Only group administrators can view the summary.")
        return

    init_group(group_id)
    g = data["groups"][group_id]

    tx_count = g.get("tx_count", 0)
    total = sum(g["users"].values())

    fee_rate = data["fees"].get(group_id, 10)
    tx_fee_total = fee_rate * tx_count * (tx_count + 1) // 2

    agent_fee_rate = data["agent_fees"].get(group_id, 0)
    agent_fee_total = int(total * (agent_fee_rate / 100.0))

    if group_id in data["licenses"]:
        try:
            expiry = datetime.strptime(data["licenses"][group_id], "%Y-%m-%d %H:%M:%S")
            days_left = (expiry - datetime.now()).days
            license_str = f"✅ Active ({days_left}d left)"
        except ValueError:
            license_str = "⚠️ Unknown"
    else:
        license_str = "❌ No license"

    members = "\n".join(
        [f"  👤 @{data['usernames'].get(uid, uid)} → {bal} TRY"
         for uid, bal in sorted(g["users"].items(), key=lambda x: x[1], reverse=True)]
    ) or "  No users yet."

    L = LANG.get(get_lang(group_id), LANG["en"])

    msg = (
        f"📋 *Group Summary*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🪪 License: {license_str}\n"
        f"💸 Transactions: `{tx_count}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👥 *Balances:*\n{members}\n\n"
        f"📊 {L['total']}: `{total} TRY`\n"
        f"📈 {L['tx_fee']} ({fee_rate}% rate): `{tx_fee_total} TRY`\n"
        f"🤝 {L['agent_fee']} ({agent_fee_rate}%): `{agent_fee_total} TRY`\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

def run_flask_panel():
    web_app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# =========================
# RUN BOT
# =========================
if __name__ == '__main__':
    print("🚀 Initializing Operational Background Threads...")

    web_worker = Thread(target=run_flask_panel, daemon=True)
    web_worker.start()

    print("🚀 Bot starting...")
    app = ApplicationBuilder().token(os.environ.get("TELEGRAM_BOT_TOKEN", "")).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(CommandHandler("keygen", keygen))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("reset", reset))

    app.add_handler(CommandHandler("allow", allow))
    app.add_handler(CommandHandler("deny", deny))
    app.add_handler(CommandHandler("whitelist", show_whitelist))
    app.add_handler(CommandHandler("setlimit", set_limit))
    app.add_handler(CommandHandler("setfee", set_fee))
    app.add_handler(CommandHandler("setagentfee", set_agent_fee)) 

    app.add_handler(CommandHandler("lang", set_lang))
    app.add_handler(CommandHandler("pdf", pdf))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("revoke", revoke))
    app.add_handler(CommandHandler("listgroups", listgroups))
    app.add_handler(CommandHandler("extendlicense", extendlicense))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("resetuser", resetuser))
    app.add_handler(CommandHandler("setbalance", setbalance))
    app.add_handler(CommandHandler("summary", summary))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("✅ Bot running...")
    app.run_polling()
