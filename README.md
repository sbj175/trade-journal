# OptionEdge

A beautiful, local web application for tracking and analyzing options trades from Tastytrade.

## Features

- 🚀 **Modern Web Interface** - Dark-themed dashboard with real-time updates
- 📊 **Performance Analytics** - Track P&L, win rate, and strategy performance
- 🔄 **Automatic Trade Recognition** - Intelligently groups multi-leg option strategies
- 📝 **Trade Management** - Add notes, update status, track your trading ideas
- 🔒 **Secure & Private** - All data stored locally, OAuth2 authentication
- 📈 **Beautiful Charts** - Visualize monthly performance and strategy breakdown

## Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: Alpine.js, Tailwind CSS, Chart.js
- **Database**: SQLite (local storage)
- **API**: Tastytrade (unofficial SDK)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/sbj175/trade-journal.git
cd trade-journal
```

2. Create a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure OAuth2 credentials:
```bash
cp .env.example .env
# Edit .env with your Tastytrade OAuth credentials:
# TASTYTRADE_PROVIDER_SECRET=your_provider_secret
# TASTYTRADE_REFRESH_TOKEN=your_refresh_token
#
# Get these from: my.tastytrade.com → Manage → My Profile → API → OAuth Applications
```

## Usage

Start the application:

```bash
# Linux/Mac
./start.sh

# Windows
start.bat

# Or manually
python app.py
```

Open your browser to: http://localhost:8000

## Configuration

### Environment Variables

Create a `.env` file with:

```env
# Tastytrade OAuth credentials
# Get from: my.tastytrade.com → Manage → My Profile → API → OAuth Applications
TASTYTRADE_PROVIDER_SECRET=your_provider_secret
TASTYTRADE_REFRESH_TOKEN=your_refresh_token

# Optional: Timezone for trade timestamps
TIMEZONE=America/New_York
```

Credentials can also be configured via the Settings page (`/settings`) in the web UI.

## Trade Recognition

The app automatically recognizes common option strategies:
- Iron Condors
- Vertical Spreads
- Covered Calls
- Cash Secured Puts
- Straddles/Strangles
- And more...

## Development

The app uses hot-reload for development:

```bash
python app.py  # Auto-reloads on file changes
```

## Security Notes

- Never commit your `.env` file (contains OAuth credentials)
- All sensitive files are excluded via `.gitignore`
- Database is stored locally in `trade_journal.db`
- No login page — app auto-connects using OAuth2 on startup

## Contributing

Feel free to open issues or submit pull requests!

## License

MIT License - see LICENSE file for details
