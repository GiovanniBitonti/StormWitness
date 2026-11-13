# StormWitness

**A simple weather-checking tool for insurance claims review.**

StormWitness is a Python application that connects two independent APIs:

- **Postcodes.io** converts a UK postcode into approximate coordinates.
- **Open-Meteo** retrieves historical wind gust and rainfall data for that location.

The application combines the results and generates a one-page HTML report indicating whether further weather review may be useful.

Weather estimates are for context only, **not proof of property damage or an insurance claims decision**.

## Requirements

- Python 3.11 or newer (3.12 recommended)
- Internet connection
- macOS or Windows
- No API keys or paid services required for this evaluation prototype

## 1. Installation

Download or clone the project, open the **StormWitness** folder in VS Code, and open a terminal.

### macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

### Windows (PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

If PowerShell blocks activation, switch the VS Code terminal to Command Prompt and run `.venv\Scripts\activate.bat`.

The virtual environment only needs to be created once. Activate it again whenever you open a new terminal.

## 2. Run StormWitness

The following commands work on both operating systems.

**Generate a weather report:**

```bash
stormwitness report "SW1A 1AA" 2023-11-02 --output report.html
```

**Open the report:**

macOS:

```bash
open report.html
```

Windows PowerShell:

```powershell
Start-Process .\report.html
```

You can also retrieve the underlying weather data as JSON:

```bash
stormwitness weather "SW1A 1AA" 2023-11-02
```

To check postcode lookup separately:

```bash
stormwitness lookup "SW1A 1AA"
```

## 3. Expected result

For the example postcode and date, our verified run returned:

| Weather indicator      | Result        |
| ---------------------- | ------------- |
| Maximum wind gust      | 70.2 km/h     |
| Daily rainfall         | 17.9 mm       |
| Further weather review | **Suggested** |

The report recommends further review because the wind gust exceeds the illustrative 65 km/h threshold.

The HTML report includes the postcode, incident date, weather values, data sources and limitations. Live historical data may change if the provider revises its datasets.

**Note:** The report command will not overwrite an existing file. Use a different output filename when running it again.

## 4. Run the tests

```bash
python -m pytest -q
```

Expected for v0.4.0:

```text
131 passed
```

Check the installed version:

```bash
stormwitness --version
```

Expected: `stormwitness 0.4.0`.

## 5. Technical notes

StormWitness validates API responses, coordinates, weather units, missing readings and UK daylight-saving transitions. It also handles network and provider errors.

The review thresholds are illustrative, not insurance-industry standards. They can be changed using `examples/review_thresholds.json`.

Further information is available in:

- `docs/TECHNICAL_WRITEUP.md` — API integration and engineering decisions
- `docs/AI_Conversation.pdf` — development prompt history
- `docs/PLAN.md` — implementation stages

**Licensing:** Open-Meteo's free API is used for non-commercial evaluation. Operational insurance use requires appropriate commercial authorisation or an alternative licensed provider.

**Version:** StormWitness v0.4.0
