# Trade Journal

A beautiful, local web application for tracking and analyzing options trades from Tastytrade.

## Features

- 🚀 **Modern Web Interface** - Dark-themed dashboard with real-time updates
- 📊 **Performance Analytics** - Track P&L, win rate, and strategy performance
- 🔄 **Automatic Trade Recognition** - Intelligently groups multi-leg option strategies
- 📝 **Trade Management** - Add notes, update status, track your trading ideas
- 🔒 **Secure & Private** - All data stored locally with encrypted credentials
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

4. Set up your credentials:
```bash
python setup_credentials.py
```

5. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your settings
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
# Optional: Direct credentials (if not using encrypted)
TASTYTRADE_USERNAME=your_username
TASTYTRADE_PASSWORD=your_password
```

### Encrypted Credentials

For better security, use encrypted credentials:

```bash
python setup_credentials.py
```

This creates:
- `crypto.key` - Encryption key
- `encrypted_credentials.py` - Encrypted credentials

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

- Never commit your `.env`, `crypto.key`, or `encrypted_credentials.py` files
- All sensitive files are excluded via `.gitignore`
- Database is stored locally in `trade_journal.db`

## Contributing

Feel free to open issues or submit pull requests!

## License

MIT License - see LICENSE file for details
