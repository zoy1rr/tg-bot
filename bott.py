from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackContext

TOKEN = "8187941791:AAEbEHd1on4Vz9g3lmSVhd9vBnct4RRcuL4"

async def start(update: Update, context: CallbackContext.DEFAULT_TYPE):
    # Inline tugma yaratish
    keyboard = [
        [InlineKeyboardButton("Open", url="https://example.com")]  # URL ni kerakli manzil bilan almashtiring
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("Salom! Tugmani bosing:", reply_markup=reply_markup)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print("Bot ishga tushdi...")
    app.run_polling()
