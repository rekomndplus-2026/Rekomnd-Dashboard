import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from scraper import GoogleMapsScraper, BusinessInfo
from sheets import save_to_sheet

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    welcome_message = (
        "Welcome to the Google Maps Scraper Bot! 🌍\n\n"
        "Send me a query using the `/search` command.\n"
        "Example: `/search real estate in cairo`\n\n"
        "To stop a running search, use the `/stop` command.\n\n"
        "I will scrape multiple businesses, collect all their reviews, and save everything into a clean Google Sheet!"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /stop command."""
    if context.user_data.get('is_scraping'):
        context.user_data['stop_scraping'] = True
        await update.message.reply_text("🛑 Stopping the scraping process. Please wait for the current business to finish...", parse_mode='Markdown')
    else:
        await update.message.reply_text("No scraping process is currently running.")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /search command."""
    if context.user_data.get('is_scraping'):
        await update.message.reply_text("⚠️ A scraping process is already running. Please use /stop to stop it before starting a new one.")
        return

    if not context.args:
        await update.message.reply_text("Please provide a search query. Example: `/search pizza in Rome`", parse_mode='Markdown')
        return

    query = " ".join(context.args)
    status_message = await update.message.reply_text(
        f"🔍 Starting mass scrape for: *{query}*...\n_This might take a few minutes as I fetch multiple businesses._\n\n_Type /stop to stop and save the progress._", 
        parse_mode='Markdown'
    )

    context.user_data['is_scraping'] = True
    context.user_data['stop_scraping'] = False

    try:
        # Increase max_reviews to 50 per business
        scraper = GoogleMapsScraper(max_reviews=50)
        
        count = 0
        saved_count = 0
        top_business_name = None

        # Iterate over the async generator (fetch all possible businesses, capped at 200 for safety against infinite loops)
        async for scraped_data in scraper.search_multiple(query, max_businesses=200):
            if context.user_data.get('stop_scraping'):
                break

            if scraped_data.error and count == 0:
                await status_message.edit_text(f"❌ *Error:* {scraped_data.error}", parse_mode='Markdown')
                return
            elif scraped_data.error:
                # If an error happens on a subsequent business, just skip it
                continue
                
            count += 1
            if count == 1:
                top_business_name = scraped_data.name

            # Save to Google Sheets
            if save_to_sheet(query, scraped_data):
                saved_count += 1

            # Update telegram message dynamically
            await status_message.edit_text(
                f"🔄 *Scraping in progress...*\n"
                f"Query: `{query}`\n"
                f"Businesses processed: {count}\n"
                f"Currently saving: _{scraped_data.name}_\n"
                f"Reviews extracted: {len(scraped_data.reviews)}\n"
                f"_Please wait... (Type /stop to interrupt)_", 
                parse_mode='Markdown'
            )

        if count == 0 and not context.user_data.get('stop_scraping'):
            await status_message.edit_text(f"⚠️ No businesses found for `{query}`.")
            return

        # Final Summary
        stopped_msg = "🛑 *Scraping Stopped by User!*\n\n" if context.user_data.get('stop_scraping') else "✅ *Scraping Complete!*\n\n"
        response_text = (
            f"{stopped_msg}"
            f"🎯 *Query:* `{query}`\n"
            f"🏢 *Businesses Scraped:* {count}\n"
            f"💾 *Saved to Sheets:* {saved_count}/{count}\n\n"
            f"🏆 *Top Result:* {top_business_name}\n\n"
            f"Check your Google Sheet! All businesses and their complete reviews have been merged into a single tab."
        )

        await status_message.edit_text(response_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error during search: {e}")
        await status_message.edit_text("❌ An unexpected error occurred while processing your request.")
    
    finally:
        context.user_data['is_scraping'] = False
        context.user_data['stop_scraping'] = False

if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set in the environment variables.")
        exit(1)

    # Initialize the Application
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("search", search_command, block=False))
    app.add_handler(CommandHandler("stop", stop_command))

    logger.info("Bot is running...")
    
    # Run the bot until the user presses Ctrl-C
    app.run_polling()

