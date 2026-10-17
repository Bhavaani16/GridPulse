GridPulse.ai SPEC

This file is the contract for every agent. If a task prompt and this file disagree, this file wins. Record the disagreement in docs/SPEC_CHANGES.md and implement this file.

JSON keys are snake_case exactly as written here. Do not rename a key in Python, TypeScript, SQL, or CSV. Timestamps are strings. Booleans are true or false. Extra JSON keys are invalid.

1. Overview

[GridPulse.ai](http://GridPulse.ai) is a campus scheduler that places flexible compute jobs, data-center cooling, and EV charging onto 24 hourly slots to reduce simulated electricity cost, marginal carbon, and cooling water. Price, marginal emissions, and curtailment come from cached CAISO-style rows, and water stress comes from a cached WRI Aqueduct-style index. A slider sets alpha from 0 to 1 as a water-reduction target: the optimizer minimizes weighted cost and carbon while keeping cooling water at or below (1 - alpha) times the naive baseline water, so alpha 0 ignores water and alpha 1 uses no wet cooling. An optimized schedule that shifts one or more jobs is not applied until a person replies YES by Photon SMS or presses the dashboard Approve button. The applied schedule turns a 5 V fan on or off through an ESP32, which posts power and temperature back to FastAPI. Metrics are stored in Tiger Data when DATABASE_URL is set, and in SQLite when it is empty. Gemini returns a short explanation of each schedule. [Fetch.ai](http://Fetch.ai) negotiation, ElevenLabs audio, Solana devnet logging, and Vultr hosting are later tiers. Every savings number is simulated. The schedule field savings_label is always the string simulated.

Tier 1, required for the demo: optimizer against the naive baseline, dashboard slider, Tiger Data with SQLite fallback, Gemini explanation with a template fallback, Photon approval with a mock fallback, ESP32 path with a simulator. Tier 2: [Fetch.ai](http://Fetch.ai) agents, ElevenLabs voiceover. Tier 3: Solana devnet, Vultr deploy. Default data mode is cached CSV. Live network data is off unless MODE=live.

2. Repo layout

Each path has one writing owner. Everyone else may read and import.

Path

Owner

Contents

/backend

Backend agent (D1)

FastAPI app, DB, simulator, schedule state machine. Does not edit the exceptions in the next table.

/frontend

Frontend agent (D2)

React dashboard.

/agents

Agents agent (D5)

[Fetch.ai](http://Fetch.ai) or local-message agents.

/firmware

Firmware agent (C3)

ESP32 project and firmware/tools/fake_[esp32.py](http://esp32.py).

/data

Data agent (C1)

Cached CSV and JSON. Read-only for every other agent.

/docs

Lead

Sponsor notes *.txt. Agents do not edit these.

/deploy

Deploy agent (D7)

Docker Compose and Vultr scripts. Tier 3 only.

/demo

Demo agent (C5)

Narration, Q&A, ElevenLabs script.

[README.md](http://README.md)

Demo agent (C5)

Root readme.

Exceptions inside /backend and /docs:

Path

Owner

/backend/optimizer

Optimizer agent (C2), including /backend/optimizer/tests

/backend/data_tools

Data agent (C1)

/backend/integrations/[photon.py](http://photon.py) and /backend/tests/test_[photon.py](http://photon.py)

Photon agent (D3)

/backend/integrations/[gemini.py](http://gemini.py) and /backend/tests/test_[gemini.py](http://gemini.py)

Gemini agent (D4)

/backend/integrations/[solana.py](http://solana.py) and /backend/tests/test_[solana.py](http://solana.py)

Solana agent (D6)

/backend/integrations/agents_[bridge.py](http://bridge.py)

Agents agent (D5)

/docs/architecture

Demo agent (C5)

docs/[DECISIONS.md](http://DECISIONS.md), docs/[PROGRESS.md](http://PROGRESS.md), docs/SPEC_[CHANGES.md](http://CHANGES.md)

Any agent may append. Nobody rewrites another agent's entries.

A fix that belongs in another owner's path is written up in docs/SPEC_[CHANGES.md](http://CHANGES.md) (what, why, which files) and worked around in the owner's own path.

[SPEC.md](http://SPEC.md)

[PROMPTS.md](http://PROMPTS.md)

.env.example

backend/

  [main.py](http://main.py)

  [schedules.py](http://schedules.py)

  decision_[log.py](http://log.py)

  [signals.py](http://signals.py)

  [simulator.py](http://simulator.py)

  Dockerfile

  optimizer/

  data_tools/

  integrations/

    [photon.py](http://photon.py)

    [gemini.py](http://gemini.py)

    [solana.py](http://solana.py)

    agents_[bridge.py](http://bridge.py)

  tests/

frontend/

agents/

firmware/

data/

docs/

deploy/

demo/

3. Stack and versions

Backend:

Python 3.11

fastapi==0.115.6

uvicorn==0.34.0

pydantic==2.10.6

httpx==0.28.1

pytest==8.3.4

scipy==1.14.1 (scipy.optimize.milp, HiGHS)

python-dotenv==1.0.1

stdlib csv, sqlite3, hashlib, json only. Do not add pandas.

Frontend:

Node.js 20

react==18.3.1, react-dom==18.3.1

vite==5.4.11

typescript==5.6.3 with "strict": true

tailwindcss==3.4.17

recharts==2.15.0

vitest==2.1.8

@testing-library/react==16.1.0

Firmware: PlatformIO, board esp32dev, framework arduino. Sensor libraries are not required to compile. See section 9.

Database: Postgres with TimescaleDB when DATABASE_URL starts with postgres:// or postgresql://. Otherwise SQLite.

TODO(human): Tiger Data connection-string format and the server's TimescaleDB version from /docs/tigerdata.txt.

Process listen address: 0.0.0.0:8000. Frontend dev server: 127.0.0.1:5173.

Every outbound HTTP call has a timeout and at most one retry, then a logged fallback. The process must start and serve the demo with MODE=cached, HARDWARE_MODE=simulated, an empty DATABASE_URL, and no network.

4. Units and time

Quantity

Unit

Field suffix or name

Electrical power of jobs, IT load, cooling split, site total

kW

power_kw, it_load_kw, yw_kw, yd_kw, ev_load_kw, total_load_kw

Energy

kWh

energy_kwh, shifted_kwh

Marginal carbon intensity

gCO2/kWh

marginal_gco2_per_kwh

Carbon mass

kg

carbon_kg

Price

$/MWh

price_usd_per_mwh

Money

USD

cost_usd

Water volume

L

water_l

Water stress

1 (dimensionless, about 0.68 to 0.76 in the sample)

water_stress_index

Curtailment

MW

curtailment_mw

Fan electrical power

W

power_w

Temperature

°C

temp_c

Slider weight

1, range 0 through 1 inclusive

alpha

power_w is the only power field in watts. Schedule loads stay in kW.

Time:

Stored timestamps are UTC ISO-8601. Hour boundaries use YYYY-MM-DDTHH:MM:SSZ. Log and telemetry timestamps may include milliseconds: YYYY-MM-DDTHH:MM:SS.mmmZ.

The optimizer horizon is 24 slots. Index t is an integer from 0 through 23.

Slot t covers [slot.ts, slot.ts + 1 hour).

In MODE=cached the horizon is CSV rows 0 through 23. On disk, horizon_start is 2026-06-21T07:00:00Z (local midnight PDT on that date). Slot t has ts = horizon_start + t hours.

Horizon rebase. HORIZON_MODE is today (default) or fixed. With fixed, every timestamp stays as written on disk. With today, the loader shifts every timestamp it loads by one constant offset so that horizon_start becomes local midnight, in HORIZON_TZ (default America/Los_Angeles), of the current local date, expressed in UTC. The offset is that new horizon_start minus 2026-06-21T07:00:00Z. The same offset applies to the CSV ts values, to every release_ts and deadline_ts in jobs.json, and to EV_FORCE_DEADLINE. Local hours therefore keep their meaning: local hour 10 stays the solar window, and a daylight-saving change only changes the UTC value. The files on disk are never modified. The rebase exists so that a real ESP32 clock (NTP, current date) and a real phone fall inside a slot. POST /api/demo/reset and startup both re-anchor to the current date. After local midnight the horizon is yesterday's, every telemetry command becomes fan on, and the lead presses Reset.

The backend reads the current time only through one function, now_utc(), so tests can patch it.

A cached file holds 48 hourly rows so a second day exists on disk. The optimizer reads 24 rows unless a later spec change says otherwise.

MODE=live asks fetch_live_signals() for 24 rows. On timeout or error it uses cached rows 0 through 23 and writes a decision-log error.

Cost conversion, used everywhere, for a 1-hour slot: cost_usd = total_load_kw  *price_usd_per_mwh / 1000. Carbon mass: carbon_kg = total_load_kw*  marginal_gco2_per_kwh / 1000. One kW for one hour is 1 kWh.

5. JSON data contracts

Pydantic v2 models live in backend/optimizer/[models.py](http://models.py). model_config is extra = "forbid". Other packages import these models. They do not redefine the fields.

5.1 GridSignal

Field

Type

ts

string, hour-aligned UTC

price_usd_per_mwh

number

marginal_gco2_per_kwh

number

curtailment_mw

number

water_stress_index

number

source

string, one of synthetic, caiso, eia, watttime, electricity_maps, wri

{

  "ts": "2026-06-21T17:00:00Z",

  "price_usd_per_mwh": 20.0,

  "marginal_gco2_per_kwh": 80.0,

  "curtailment_mw": 250.0,

  "water_stress_index": 0.6852,

  "source": "synthetic"

}

/data/signals_cached.csv header row, in this order:

ts,price_usd_per_mwh,marginal_gco2_per_kwh,curtailment_mw,water_stress_index,source

48 data rows, index i from 0 through 47. local_hour = i % 24. ts is 2026-06-21T07:00:00Z plus i hours. source is synthetic for every committed row. Values for local_hour:

local_hour

price_usd_per_mwh

marginal_gco2_per_kwh

curtailment_mw

water_stress_index

0

45.0

250.0

5.0

0.7455

1

45.0

250.0

5.0

0.7380

2

45.0

250.0

5.0

0.7293

3

45.0

250.0

5.0

0.7200

4

45.0

250.0

5.0

0.7107

5

45.0

250.0

5.0

0.7020

6

45.0

250.0

5.0

0.6945

7

45.0

250.0

5.0

0.6888

8

45.0

250.0

5.0

0.6852

9

45.0

250.0

5.0

0.6840

10

20.0

80.0

250.0

0.6852

11

20.0

80.0

250.0

0.6888

12

20.0

80.0

250.0

0.6945

13

20.0

80.0

250.0

0.7020

14

20.0

80.0

250.0

0.7107

15

20.0

80.0

250.0

0.7200

16

45.0

250.0

40.0

0.7293

17

45.0

250.0

40.0

0.7380

18

90.0

420.0

5.0

0.7455

19

90.0

420.0

5.0

0.7512

20

90.0

420.0

5.0

0.7548

21

45.0

250.0

5.0

0.7560

22

45.0

250.0

5.0

0.7548

23

45.0

250.0

5.0

0.7512

Write price, carbon, and curtailment with one decimal place and water stress with four. The sum of water_stress_index over rows 0 through 23 is 17.28. Row 24 repeats local hour 0 at ts 2026-06-22T07:00:00Z. These rows are the committed cache. A live fetch must not overwrite this file.

The closed form that produced water_stress_index is round(0.72  *(1 + 0.05*  sin(2  *pi*  (local_hour - 15) / 24)), 4) using Python math.sin and Python round. The table wins if a reimplementation disagrees.

TODO(human): CAISO OASIS, EIA, WattTime, Electricity Maps, and WRI Aqueduct request URLs and parameters from /docs/data_sources.txt. Until that file lists an URL, fetch_[signals.py](http://signals.py) writes the table above and does not open a socket.

5.2 Job

Field

Type

Rule

job_id

string

Unique, pattern ^[a-z0-9-]{1,64}$

name

string

kind

string

compute or ev_charge

checkpointable

boolean

false requires integer duration_h

asset_id

string

compute uses the data-center asset. ev_charge uses the EV-hub asset.

power_kw

number

> 0

duration_h

number

> 0. For checkpointable: false, a positive integer.

energy_kwh

number

Must equal power_kw * duration_h within 1e-6

release_ts

string

UTC, hour-aligned

deadline_ts

string

UTC, hour-aligned, strictly after release_ts

A slot is inside the window when release_ts <= slot.ts and slot.ts + 1 hour <= deadline_ts.

/data/jobs.json is this array and nothing else:

[

  {"job_id": "job-cp-01", "name": "Nightly ETL", "kind": "compute", "checkpointable": true, "asset_id": "asset-dc-01", "power_kw": 5.0, "duration_h": 4, "energy_kwh": 20.0, "release_ts": "2026-06-21T07:00:00Z", "deadline_ts": "2026-06-22T07:00:00Z"},

  {"job_id": "job-cp-02", "name": "Feature build", "kind": "compute", "checkpointable": true, "asset_id": "asset-dc-01", "power_kw": 4.0, "duration_h": 3, "energy_kwh": 12.0, "release_ts": "2026-06-21T15:00:00Z", "deadline_ts": "2026-06-22T03:00:00Z"},

  {"job_id": "job-cp-03", "name": "Model eval", "kind": "compute", "checkpointable": true, "asset_id": "asset-dc-01", "power_kw": 6.0, "duration_h": 2, "energy_kwh": 12.0, "release_ts": "2026-06-21T13:00:00Z", "deadline_ts": "2026-06-22T05:00:00Z"},

  {"job_id": "job-cp-04", "name": "Log compaction", "kind": "compute", "checkpointable": true, "asset_id": "asset-dc-01", "power_kw": 3.0, "duration_h": 5, "energy_kwh": 15.0, "release_ts": "2026-06-21T07:00:00Z", "deadline_ts": "2026-06-22T07:00:00Z"},

  {"job_id": "job-ncp-01", "name": "GPU training", "kind": "compute", "checkpointable": false, "asset_id": "asset-dc-01", "power_kw": 4.0, "duration_h": 3, "energy_kwh": 12.0, "release_ts": "2026-06-21T07:00:00Z", "deadline_ts": "2026-06-22T07:00:00Z"},

  {"job_id": "job-ncp-02", "name": "Video transcode", "kind": "compute", "checkpointable": false, "asset_id": "asset-dc-01", "power_kw": 5.0, "duration_h": 2, "energy_kwh": 10.0, "release_ts": "2026-06-21T16:00:00Z", "deadline_ts": "2026-06-22T05:00:00Z"},

  {"job_id": "job-ev-01", "name": "Fleet top-up", "kind": "ev_charge", "checkpointable": true, "asset_id": "asset-ev-01", "power_kw": 7.0, "duration_h": 4, "energy_kwh": 28.0, "release_ts": "2026-06-21T07:00:00Z", "deadline_ts": "2026-06-22T01:00:00Z"},

  {"job_id": "job-ev-02", "name": "Shuttle charge", "kind": "ev_charge", "checkpointable": false, "asset_id": "asset-ev-01", "power_kw": 11.0, "duration_h": 2, "energy_kwh": 22.0, "release_ts": "2026-06-21T19:00:00Z", "deadline_ts": "2026-06-22T07:00:00Z"}

]

5.3 Asset

Field

Type

Rule

asset_id

string

kind

string

data_center or ev_hub

name

string

it_capacity_kw

number or null

Required number for data_center, null for ev_hub

charge_capacity_kw

number or null

Required number for ev_hub, null for data_center

wet_extra_kw_per_kw

number or null

kW of cooling electricity per kW of IT on wet cooling. Null for ev_hub.

dry_extra_kw_per_kw

number or null

Same, for dry cooling. Null for ev_hub.

wet_water_l_per_kwh

number or null

Liters of water per kWh of IT served by wet cooling, before multiplying by water stress. Null for ev_hub.

The sample has one asset of each kind. The solver rejects any other count.

/data/assets.json:

[

  {

    "asset_id": "asset-dc-01",

    "kind": "data_center",

    "name": "Campus DC",

    "it_capacity_kw": 20.0,

    "charge_capacity_kw": null,

    "wet_extra_kw_per_kw": 0.15,

    "dry_extra_kw_per_kw": 0.35,

    "wet_water_l_per_kwh": 1.8

  },

  {

    "asset_id": "asset-ev-01",

    "kind": "ev_hub",

    "name": "Campus EV Hub",

    "it_capacity_kw": null,

    "charge_capacity_kw": 50.0,

    "wet_extra_kw_per_kw": null,

    "dry_extra_kw_per_kw": null,

    "wet_water_l_per_kwh": null

  }

]

Wet cooling spends 0.15 kW extra electricity and 1.8 L * water_stress_index of water per kW of IT. Dry cooling spends 0.35 kW extra electricity and 0 L of water per kW of IT.

5.4 Schedule

Field

Type

Rule

schedule_id

string

Baseline id is sch-baseline. Optimized ids are sch- + YYYYMMDDTHHMMSSZ + -a + three-digit round(alpha * 100), example sch-20260621T190000Z-a050. If a schedule with that id already exists (two optimize calls at the same alpha in the same second), append -b, then -c, and so on to the new id.

schedule_kind

string

baseline or optimized

status

string

One of proposed, pending_approval, approved, applied, rejected, expired, superseded

alpha

number

0 through 1. Baseline stores 0.0.

horizon_start

string

UTC

created_at

string

UTC

slots

array of Slot

Length 24, t = 0,1,...,23 in that order

metrics

Metrics

This schedule

baseline_metrics

Metrics

Baseline on the same signals

savings_pct

SavingsPct

From the shared function in section 7

shifted_job_count

integer

shifted_kwh

number

savings_label

string

Always simulated

explanation

string or null

Slot

Field

Type

t

integer 0..23

ts

string

cooling_mode

wet or dry

it_load_kw

number

yw_kw

number, IT kW served by wet cooling

yd_kw

number, IT kW served by dry cooling

ev_load_kw

number

total_load_kw

number

jobs

array of {"job_id": string, "fraction": number}

fraction is x[j,t]. Omit jobs whose fraction is 0. cooling_mode is dry when yd_kw > yw_kw, otherwise wet.

Metrics: cost_usd, carbon_kg, water_l, energy_kwh, all numbers.

SavingsPct: cost, carbon, water, all numbers. Positive means the optimized schedule is lower than the baseline.

{

  "schedule_id": "sch-20260621T190000Z-a050",

  "schedule_kind": "optimized",

  "status": "proposed",

  "alpha": 0.5,

  "horizon_start": "2026-06-21T07:00:00Z",

  "created_at": "2026-06-21T19:00:00Z",

  "slots": [

    {

      "t": 0,

      "ts": "2026-06-21T07:00:00Z",

      "cooling_mode": "wet",

      "it_load_kw": 5.0,

      "yw_kw": 5.0,

      "yd_kw": 0.0,

      "ev_load_kw": 7.0,

      "total_load_kw": 12.75,

      "jobs": [

        {"job_id": "job-cp-01", "fraction": 1.0},

        {"job_id": "job-ev-01", "fraction": 1.0}

      ]

    }

  ],

  "metrics": {"cost_usd": 12.4, "carbon_kg": 18.2, "water_l": 90.0, "energy_kwh": 110.0},

  "baseline_metrics": {"cost_usd": 14.0, "carbon_kg": 21.0, "water_l": 100.0, "energy_kwh": 115.0},

  "savings_pct": {"cost": 11.428571, "carbon": 13.333333, "water": 10.0},

  "shifted_job_count": 3,

  "shifted_kwh": 44.0,

  "savings_label": "simulated",

  "explanation": null

}

The object above is a shape example. A stored schedule has 24 slots. The numbers in this example are not the optimizer's required output. total_load_kw on slot 0 of the example is 5 + 0.15 * 5 + 0 + 7 = 12.75.

A job is shifted when some slot's fraction differs from the baseline fraction by more than 1e-6. shifted_job_count is how many jobs are shifted. shifted_kwh is the sum of energy_kwh over those jobs.

The baseline row stored at startup:

schedule_id: sch-baseline

schedule_kind: baseline

status: applied

alpha: 0.0

savings_pct: {"cost": 0.0, "carbon": 0.0, "water": 0.0}

metrics equals baseline_metrics

shifted_job_count: 0

shifted_kwh: 0.0

savings_label: simulated

5.5 DecisionLogEntry

Field

Type

Rule

log_id

string

log- plus 12 lowercase hex chars

ts

string

UTC

schedule_id

string or null

actor

string

One of system, optimizer, dashboard, photon, gemini, solana, grid-agent, dc-agent, ev-agent, bridge, simulator

event

string

One of the names in the table below

payload

object

Keys listed below. Extra keys invalid.

event

payload keys

startup

mode (string), hardware_mode (string)

proposed

alpha (number), shifted_job_count (integer), shifted_kwh (number)

approval_requested

shifted_job_count (integer), shifted_kwh (number)

sms_sent

message_id (string), phone_masked (string), text (string)

sms_reply

message_id (string), phone_masked (string), text (string)

clarification_sent

message_id (string), text (string)

approved

via (sms or dashboard)

rejected

reason (sms_no or dashboard)

applied

previous_schedule_id (string)

expired

reason (timeout or superseded_by_new_request)

superseded

replaced_by (string)

reset

applied_schedule_id (string)

error

integration (string), message (string)

explanation

source (gemini, fallback, or cache), text (string)

negotiation_msg

the agent envelope from section 12

settlement_tx

signature (string), explorer_url (string or null), mode (mock or live)

telemetry_flagged

device_id (string), power_w (number), temp_c (number)

{

  "log_id": "log-a1b2c3d4e5f6",

  "ts": "2026-06-21T19:00:01.000Z",

  "schedule_id": "sch-20260621T190000Z-a050",

  "actor": "optimizer",

  "event": "proposed",

  "payload": {"alpha": 0.5, "shifted_job_count": 3, "shifted_kwh": 44.0}

}

Phone masking: keep the last two characters of the phone string and replace every earlier character with *. A string shorter than 2 characters is logged as* **. Do not log the unmasked number.

5.6 Telemetry

POST body and the firmware JSON:

Field

Type

Rule

device_id

string

Pattern ^[A-Za-z0-9_-]{1,64}$

ts

string

UTC

power_w

number

temp_c

number

fan_on

boolean

Device's current output, not the desired command

simulated

boolean

true for the Python simulator and fake_[esp32.py](http://esp32.py) test mode. false for the ESP32.

{

  "device_id": "esp32-fan-01",

  "ts": "2026-06-21T19:00:02.000Z",

  "power_w": 4.5,

  "temp_c": 31.5,

  "fan_on": true,

  "simulated": false

}

Range: power_w inside 0 through 500 inclusive, temp_c inside -20 through 120 inclusive. Outside that range the row is stored with server field flagged=true, a telemetry_flagged log entry is written, and the row is excluded from GET /api/telemetry. The fan command still comes from the applied schedule, not from the reading.

5.7 Constraints

Optional input to optimize. Both keys optional. Extra keys invalid.

Field

Type

max_it_kw

number, optional. When present, it_load_kw at every slot is at most this value.

job_deadlines

object mapping job_id to a UTC timestamp, optional. Each value tightens that job's deadline to the earlier of the two instants.

{"max_it_kw": 6.0, "job_deadlines": {"job-ev-02": "2026-06-21T21:00:00Z"}}

5.8 OptimizeError

Returned by optimize and baseline. Never raise for an infeasible job or a failed solve.

Field

Type

code

infeasible or solver_error

message

string

job_id

string or null

For infeasible, message is job {job_id} cannot complete inside its window and job_id is set. For solver_error, job_id is null.

{"code": "infeasible", "message": "job job-cp-03 cannot complete inside its window", "job_id": "job-cp-03"}

6. REST API

Base URL in development: [http://127.0.0.1:8000](http://127.0.0.1:8000). CORS allow-origin is the value of CORS_ORIGINS (default [http://localhost:5173](http://localhost:5173)). Responses are application/json except GET /api/stream.

Error body, used for every non-2xx JSON response:

{

  "error": {

    "code": "validation_error",

    "message": "alpha must be between 0 and 1",

    "details": {"field": "alpha"}

  }

}

HTTP

code

When

422

validation_error

Body or query failed Pydantic or a range check on an input field

422

infeasible

OptimizeError.code == infeasible. details.job_id is the job.

422

solver_error

Solver failed. details is the OptimizeError object.

404

not_found

Unknown schedule_id

409

invalid_state

Illegal status transition. details includes schedule_id and status.

501

photon_unconfigured

PHOTON_MODE=live and /docs/photon.txt has no field mapping

500

internal_error

Bug. Integrations must not use this path for timeouts.

{

  "error": {

    "code": "invalid_state",

    "message": "cannot approve a schedule in status applied",

    "details": {"schedule_id": "sch-baseline", "status": "applied"}

  }

}

Method

Path

Request

Response

GET

/api/health

none

Health

GET

/api/signals

none

{"horizon_start", "items": [GridSignal x24]}

GET

/api/jobs

none

{"items": [Job]}

GET

/api/assets

none

{"items": [Asset]}

POST

/api/optimize

OptimizeRequest

Schedule, status proposed

GET

/api/schedules/applied

none

The one schedule with status applied

GET

/api/schedules/{schedule_id}

none

Schedule

POST

/api/schedules/{schedule_id}/request-approval

empty body

Schedule

POST

/api/schedules/{schedule_id}/approve

empty body

Schedule, status applied

POST

/api/schedules/{schedule_id}/reject

empty body

Schedule, status rejected

GET

/api/explain/{schedule_id}

none

ExplainResponse

GET

/api/decisions?limit=50&after={log_id}

query

{"items": [DecisionLogEntry]} ascending by ts

POST

/api/telemetry

Telemetry

{"command": {"fan_on": bool}}

GET

/api/telemetry?minutes=5

query, default 5, max 60

{"items": [TelemetryMinute]}

GET

/api/stream

none

text/event-stream

POST

/api/demo/trigger-surplus

empty body

Schedule

POST

/api/demo/reset

empty body

{"status": "ok", "applied_schedule_id": "sch-baseline"}

POST

/api/webhooks/photon

section 10

WebhookResult

Health

{

  "status": "ok",

  "mode": "cached",

  "hardware_mode": "simulated",

  "database": "sqlite",

  "optimizer_mode": "real",

  "photon_mode": "mock",

  "gemini_mode": "mock",

  "solana_mode": "mock",

  "agents_mode": "local"

}

database is sqlite or postgres. mode is cached or live. hardware_mode is simulated or real.

OptimizeRequest

{"alpha": 0.5, "constraints": null}

constraints may be omitted. alpha outside 0 through 1 is 422 validation_error.

POST /api/optimize runs optimize on the in-memory signals, stores the schedule as proposed, writes event proposed, and returns it. It does not send SMS and it does not call negotiate.

ExplainResponse

{

  "schedule_id": "sch-20260621T190000Z-a050",

  "text": "Simulated result at alpha 0.50: this schedule costs $12.40, emits 18.20 kg CO2, and uses 90.0 L of water, which is +11.4% cost, +13.3% carbon, and +10.0% water versus the naive baseline. Jobs moved: 3. Cooling follows the wet/dry split in the schedule.",

  "source": "fallback"

}

source is gemini, fallback, or cache.

TelemetryMinute

{

  "bucket": "2026-06-21T19:01:00Z",

  "device_id": "esp32-fan-sim",

  "power_w": 4.5,

  "temp_c": 30.1,

  "fan_on": true,

  "simulated": true

}

bucket is the UTC minute start. power_w and temp_c are averages of non-flagged rows in that minute. fan_on is true if any row in the minute has fan_on: true. simulated is true if any row has simulated: true. On Postgres, read the continuous aggregate telemetry_1m. On SQLite, compute the same grouping in Python. Order items by bucket ascending.

WebhookResult

{"status": "applied", "schedule_id": "sch-20260621T190000Z-a050", "clarification": false}

status is applied, rejected, pending_approval, or ignored. When status is ignored, include reason with value duplicate or not_pending and omit schedule_id.

SSE. GET /api/stream sends the latest 20 decision rows on connect, then each new row. Heartbeat comment every 15 seconds: a line : ping.

event: decision

data: {"log_id":"log-a1b2c3d4e5f6","ts":"2026-06-21T19:00:01.000Z","schedule_id":"sch-20260621T190000Z-a050","actor":"optimizer","event":"proposed","payload":{"alpha":0.5,"shifted_job_count":3,"shifted_kwh":44.0}}

GET /api/decisions is required even when SSE exists. limit default 50, max 200. after is exclusive.

Demo trigger. POST /api/demo/trigger-surplus copies the in-memory 24 signals and edits four slots. Let t0 be the slot index whose interval contains the current UTC time. If none does, t0 is 10. For each t in {t0, t0+1, t0+2, t0+3} that is inside 0..23:

curtailment_mw = curtailment_mw + 300

price_usd_per_mwh = price_usd_per_mwh * 0.5

marginal_gco2_per_kwh = marginal_gco2_per_kwh * 0.5

The CSV file is not modified. Then call optimize at the alpha of the latest POST /api/optimize, or 0.5 if there has been none. Then call negotiate on that schedule (the Tier 1 stub returns the same schedule). Store proposed. If shifted_job_count > 0, call request_approval. If shifted_job_count == 0, call approve_and_apply with actor optimizer. Return the stored schedule. The handler returns within 3 seconds when Photon, Gemini, Solana, and agents are in mock or local mode.

On the committed sample and the section 7 solver, this endpoint returns shifted_job_count >= 1 and status pending_approval.

Demo reset. Delete every schedule, decision-log row, and telemetry row. Clear the Gemini cache. Reload signals from the CSV and re-apply the HORIZON_MODE rebase for the current date. Rebuild sch-baseline with status applied. Write one reset log. Return the JSON in the table.

Startup. Load CSV and JSON, then apply the HORIZON_MODE rebase from section 4. Exit code 1 if those files fail validation. Create tables. If sch-baseline is missing, build it with baseline() and store it as applied. Write startup. If START_SIMULATOR=1, start the simulator loop. A missing optional integration module is an error log, not a crash. OPTIMIZER_MODE=mock uses backend/mocks/optimizer_[mock.py](http://mock.py), which must expose optimize(signals, jobs, assets, alpha, constraints=None) and baseline(signals, jobs, assets) and return a feasible schedule for the sample data.

Internal signatures (D1 creates the modules; later agents replace the function bodies and do not change the signatures):

backend/optimizer/[solver.py](http://solver.py)

  optimize(signals, jobs, assets, alpha, constraints=None) -> Schedule | OptimizeError

backend/optimizer/[baseline.py](http://baseline.py)

  baseline(signals, jobs, assets) -> Schedule | OptimizeError

backend/optimizer/[metrics.py](http://metrics.py)

  compute_metrics(signals, slots, assets) -> Metrics

  savings_pct(optimized: Metrics, baseline: Metrics) -> SavingsPct

  metrics_hash(metrics: Metrics) -> str

backend/[schedules.py](http://schedules.py)

  request_approval(schedule_id: str, actor: str) -> Schedule

  approve_and_apply(schedule_id: str, actor: str) -> Schedule

  reject(schedule_id: str, actor: str) -> Schedule

  expire(schedule_id: str, actor: str) -> Schedule

backend/decision_[log.py](http://log.py)

  write_log(schedule_id: str | None, actor: str, event: str, payload: dict) -> DecisionLogEntry

backend/integrations/[photon.py](http://photon.py)

  send_approval_sms(schedule: Schedule) -> str

  photon_router: APIRouter mounted at /api/webhooks

backend/integrations/[gemini.py](http://gemini.py)

  explain(schedule: Schedule, signals: list[GridSignal], prev_schedule: Schedule | None) -> str

backend/integrations/[solana.py](http://solana.py)

  record_settlement(schedule: Schedule) -> str | None

backend/integrations/agents_[bridge.py](http://bridge.py)

  negotiate(schedule: Schedule) -> Schedule

backend/data_tools/[live.py](http://live.py)

  fetch_live_signals() -> list[GridSignal]

photon_router routes POST "" so the public path is POST /api/webhooks/photon.

Stub behavior until the owning agent lands: send_approval_sms returns mock-sms- + schedule_id and writes sms_sent. explain returns the section 11 template. record_settlement returns None. negotiate returns its input. fetch_live_signals returns cached rows 0..23. Stubs do not open sockets.

make dev from /backend runs uvicorn main:app --reload --host 0.0.0.0 --port 8000. make test runs pytest.

7. Optimizer

Pure functions. No network. No global mutable state. Same inputs produce the same schedule. Job loops walk job_id ascending.

Sets

T = {0,1,...,23}

J = all jobs

J_cp = jobs with checkpointable == true

J_ncp = jobs with checkpointable == false

W_j = slot indexes inside the job window, after applying constraints.job_deadlines when present

F_j for j in J_ncp = start indexes t such that t, t+1, ..., t+duration_h-1 are all inside W_j

Parameters

From each GridSignal, Job, and Asset. Cooling coefficients come from asset-dc-01: wet_extra_kw_per_kw = 0.15, dry_extra_kw_per_kw = 0.35, wet_water_l_per_kwh = 1.8.

Variables

x[j,t] continuous in [0, 1] for every job and every t in W_j, and fixed at 0 outside W_j

s[j,t] binary for each j in J_ncp and each t in F_j

yw[t] >= 0, yd[t] >= 0 in kW

Solve with one scipy.optimize.milp call. Continuous variables have integrality 0. s has integrality 1. HiGHS time_limit is 1.5 seconds. mip_rel_gap is 1e-4.

Constraints

Completion: for each job, sum_t x[j,t] = duration_h.

Window: x[j,t] = 0 for t not in W_j.

Non-checkpointable start: for each j in J_ncp, sum_{t in F_j} s[j,t] = 1.

Non-checkpointable link: x[j,tau] = sum of s[j,t] over starts t in F_j with t <= tau <= t+duration_h-1. Therefore a non-checkpointable job is a contiguous block of ones.

IT load: it_load_kw[t] = sum of power_kw * x[j,t] over kind=compute.

EV load: ev_load_kw[t] = sum of power_kw * x[j,t] over kind=ev_charge.

Cooling split: yw[t] + yd[t] = it_load_kw[t]. EV load is not cooled.

Capacity: it_load_kw[t] <= it_capacity_kw (20 in the sample). ev_load_kw[t] <= charge_capacity_kw (50 in the sample).

Optional: if constraints.max_it_kw is set, it_load_kw[t] <= max_it_kw for every t.

If F_j is empty or the window has fewer slot-hours than duration_h, return OptimizeError for that job_id and do not call the solver.

Site power:

total_load_kw[t] = it_load_kw[t]

  + wet_extra_kw_per_kw * yw[t]

  + dry_extra_kw_per_kw * yd[t]

  + ev_load_kw[t]

Objective

Compute the baseline first (below) and its metrics cost_base, carbon_base, water_base.

minimize

  0.3 * cost_term

  + (1 - alpha) * carbon_term

  + alpha * water_term

cost_term is cost_usd / cost_base when cost_base > 0, else the cost term is omitted (coefficient 0). The same rule applies to carbon and water. Do not divide by zero.

cost_usd   = sum_t total_load_kw[t] * price_usd_per_mwh[t] / 1000

carbon_kg  = sum_t total_load_kw[t] * marginal_gco2_per_kwh[t] / 1000

water_l    = sum_t wet_water_l_per_kwh  *yw[t]*  water_stress_index[t]

energy_kwh = sum_t total_load_kw[t]

yw and yd stay linear. There is no binary cooling variable and no product of alpha with a variable inside the solver: alpha only changes the three numeric coefficients.

Round each stored fraction and each metric to 6 decimal places.

Baseline

baseline(signals, jobs, assets) places every job as a contiguous block at full power (x=1 for each whole hour) starting at the earliest slot in W_j. If duration_h is not an integer, the last placed hour of a checkpointable job gets the fractional remainder. yd[t] = 0 and yw[t] = it_load_kw[t] for every slot. If a job's block does not fit in W_j, return OptimizeError for that job.

The committed sample is feasible for this baseline, and the baseline IT load is at most 20 kW in every hour.

Shared metrics

compute_metrics is the only implementation of the four sums above. baseline and optimize both call it. savings_pct is the only implementation of:

savings_pct.cost   = (cost_base - cost_usd) / cost_base * 100   if cost_base > 0 else 0

savings_pct.carbon = (carbon_base - carbon_kg) / carbon_base * 100   if carbon_base > 0 else 0

savings_pct.water  = (water_base - water_l) / water_base * 100   if water_base > 0 else 0

metrics_hash is SHA-256 hex of the UTF-8 bytes of json.dumps(body, sort_keys=True, separators=(",", ":")) where body is:

{"carbon_kg": 0.0, "cost_usd": 0.0, "energy_kwh": 0.0, "water_l": 0.0}

with each value round(value, 6) before dumping.

CLI

From /backend: python -m optimizer.cli --alpha 0.5

Loads ../data/signals_cached.csv rows 0..23, ../data/jobs.json, and ../data/assets.json. Prints one row per hour with columns t, it_kw_base, it_kw_opt, cooling_base, cooling_opt, price_usd_per_mwh, marginal_gco2_per_kwh, curtailment_mw, then one line with both Metrics objects and SavingsPct.

backend/optimizer/[FORMULATION.md](http://FORMULATION.md) explains this section in plain language, including why yw and yd are separate.

8. SQL schema

Run the matching block at startup. Running it twice is a no-op.

SQLite (empty DATABASE_URL, or a URL starting with sqlite:///):

Empty DATABASE_URL stores the file at backend/.local/gridpulse.db.

sqlite:///RELATIVE/PATH stores that path.

JSON columns are TEXT holding one JSON object or array.

Timestamps are TEXT in the UTC form from section 4.

Do not call Timescale functions.

GET /api/telemetry aggregates in Python.

CREATE TABLE IF NOT EXISTS grid_signals (

  ts TEXT PRIMARY KEY,

  price_usd_per_mwh REAL NOT NULL,

  marginal_gco2_per_kwh REAL NOT NULL,

  curtailment_mw REAL NOT NULL,

  water_stress_index REAL NOT NULL,

  source TEXT NOT NULL

);

CREATE TABLE IF NOT EXISTS assets (

  asset_id TEXT PRIMARY KEY,

  kind TEXT NOT NULL,

  name TEXT NOT NULL,

  it_capacity_kw REAL,

  charge_capacity_kw REAL,

  wet_extra_kw_per_kw REAL,

  dry_extra_kw_per_kw REAL,

  wet_water_l_per_kwh REAL

);

CREATE TABLE IF NOT EXISTS jobs (

  job_id TEXT PRIMARY KEY,

  name TEXT NOT NULL,

  kind TEXT NOT NULL,

  checkpointable INTEGER NOT NULL,

  asset_id TEXT NOT NULL,

  power_kw REAL NOT NULL,

  duration_h REAL NOT NULL,

  energy_kwh REAL NOT NULL,

  release_ts TEXT NOT NULL,

  deadline_ts TEXT NOT NULL

);

CREATE TABLE IF NOT EXISTS schedules (

  schedule_id TEXT PRIMARY KEY,

  schedule_kind TEXT NOT NULL,

  status TEXT NOT NULL,

  alpha REAL NOT NULL,

  horizon_start TEXT NOT NULL,

  created_at TEXT NOT NULL,

  metrics_json TEXT NOT NULL,

  baseline_metrics_json TEXT NOT NULL,

  savings_pct_json TEXT NOT NULL,

  shifted_job_count INTEGER NOT NULL,

  shifted_kwh REAL NOT NULL,

  savings_label TEXT NOT NULL,

  explanation TEXT

);

CREATE TABLE IF NOT EXISTS schedule_slots (

  schedule_id TEXT NOT NULL,

  t INTEGER NOT NULL,

  ts TEXT NOT NULL,

  cooling_mode TEXT NOT NULL,

  it_load_kw REAL NOT NULL,

  yw_kw REAL NOT NULL,

  yd_kw REAL NOT NULL,

  ev_load_kw REAL NOT NULL,

  total_load_kw REAL NOT NULL,

  jobs_json TEXT NOT NULL,

  PRIMARY KEY (schedule_id, t)

);

CREATE TABLE IF NOT EXISTS decision_log (

  log_id TEXT PRIMARY KEY,

  ts TEXT NOT NULL,

  schedule_id TEXT,

  actor TEXT NOT NULL,

  event TEXT NOT NULL,

  payload_json TEXT NOT NULL

);

CREATE TABLE IF NOT EXISTS telemetry (

  device_id TEXT NOT NULL,

  ts TEXT NOT NULL,

  power_w REAL NOT NULL,

  temp_c REAL NOT NULL,

  fan_on INTEGER NOT NULL,

  simulated INTEGER NOT NULL,

  flagged INTEGER NOT NULL DEFAULT 0,

  PRIMARY KEY (device_id, ts)

);

Postgres / Tiger Data. Connect with a 5-second timeout and one retry. On failure, log error with integration tigerdata and open SQLite instead. Do not exit.

TODO(human): the DATABASE_URL format from /docs/tigerdata.txt.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS grid_signals (

  ts TIMESTAMPTZ PRIMARY KEY,

  price_usd_per_mwh DOUBLE PRECISION NOT NULL,

  marginal_gco2_per_kwh DOUBLE PRECISION NOT NULL,

  curtailment_mw DOUBLE PRECISION NOT NULL,

  water_stress_index DOUBLE PRECISION NOT NULL,

  source TEXT NOT NULL

);

CREATE TABLE IF NOT EXISTS assets (

  asset_id TEXT PRIMARY KEY,

  kind TEXT NOT NULL,

  name TEXT NOT NULL,

  it_capacity_kw DOUBLE PRECISION,

  charge_capacity_kw DOUBLE PRECISION,

  wet_extra_kw_per_kw DOUBLE PRECISION,

  dry_extra_kw_per_kw DOUBLE PRECISION,

  wet_water_l_per_kwh DOUBLE PRECISION

);

CREATE TABLE IF NOT EXISTS jobs (

  job_id TEXT PRIMARY KEY,

  name TEXT NOT NULL,

  kind TEXT NOT NULL,

  checkpointable BOOLEAN NOT NULL,

  asset_id TEXT NOT NULL,

  power_kw DOUBLE PRECISION NOT NULL,

  duration_h DOUBLE PRECISION NOT NULL,

  energy_kwh DOUBLE PRECISION NOT NULL,

  release_ts TIMESTAMPTZ NOT NULL,

  deadline_ts TIMESTAMPTZ NOT NULL

);

CREATE TABLE IF NOT EXISTS schedules (

  schedule_id TEXT PRIMARY KEY,

  schedule_kind TEXT NOT NULL,

  status TEXT NOT NULL,

  alpha DOUBLE PRECISION NOT NULL,

  horizon_start TIMESTAMPTZ NOT NULL,

  created_at TIMESTAMPTZ NOT NULL,

  metrics_json JSONB NOT NULL,

  baseline_metrics_json JSONB NOT NULL,

  savings_pct_json JSONB NOT NULL,

  shifted_job_count INTEGER NOT NULL,

  shifted_kwh DOUBLE PRECISION NOT NULL,

  savings_label TEXT NOT NULL,

  explanation TEXT

);

CREATE TABLE IF NOT EXISTS schedule_slots (

  schedule_id TEXT NOT NULL REFERENCES schedules(schedule_id),

  t INTEGER NOT NULL,

  ts TIMESTAMPTZ NOT NULL,

  cooling_mode TEXT NOT NULL,

  it_load_kw DOUBLE PRECISION NOT NULL,

  yw_kw DOUBLE PRECISION NOT NULL,

  yd_kw DOUBLE PRECISION NOT NULL,

  ev_load_kw DOUBLE PRECISION NOT NULL,

  total_load_kw DOUBLE PRECISION NOT NULL,

  jobs_json JSONB NOT NULL,

  PRIMARY KEY (schedule_id, t)

);

CREATE TABLE IF NOT EXISTS decision_log (

  log_id TEXT NOT NULL,

  ts TIMESTAMPTZ NOT NULL,

  schedule_id TEXT,

  actor TEXT NOT NULL,

  event TEXT NOT NULL,

  payload_json JSONB NOT NULL,

  PRIMARY KEY (log_id, ts)

);

CREATE TABLE IF NOT EXISTS telemetry (

  device_id TEXT NOT NULL,

  ts TIMESTAMPTZ NOT NULL,

  power_w DOUBLE PRECISION NOT NULL,

  temp_c DOUBLE PRECISION NOT NULL,

  fan_on BOOLEAN NOT NULL,

  simulated BOOLEAN NOT NULL,

  flagged BOOLEAN NOT NULL DEFAULT FALSE,

  PRIMARY KEY (device_id, ts)

);

SELECT create_hypertable('decision_log', 'ts', if_not_exists => TRUE);

SELECT create_hypertable('telemetry', 'ts', if_not_exists => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_1m

WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS

SELECT

  time_bucket('1 minute', ts) AS bucket,

  device_id,

  avg(power_w) AS power_w,

  avg(temp_c) AS temp_c,

  bool_or(fan_on) AS fan_on,

  bool_or(simulated) AS simulated

FROM telemetry

WHERE flagged = FALSE

GROUP BY bucket, device_id

WITH NO DATA;

SELECT add_continuous_aggregate_policy(

  'telemetry_1m',

  start_offset => INTERVAL '1 hour',

  end_offset => INTERVAL '1 minute',

  schedule_interval => INTERVAL '1 minute',

  if_not_exists => TRUE

);

If CREATE EXTENSION, either hypertable call, or the telemetry_1m creation fails, log error and keep serving with the plain Postgres tables plus Python aggregation. Column names stay the same. timescaledb.materialized_only = false turns on real-time aggregation, so the newest minute is visible without waiting for the refresh policy (without it the live telemetry chart can trail by a minute or two). If the server's TimescaleDB version rejects that option, create the view without it and have GET /api/telemetry aggregate the raw telemetry table with time_bucket instead.

TODO(human): confirm the real-time aggregate option for the server's TimescaleDB version from /docs/tigerdata.txt.

At most one row in schedules has status = 'applied'. At most one row has status = 'pending_approval'.

9. ESP32 protocol, safety, simulator

The fan command is a function of the applied schedule only:

fan_on command =

  true   if there is no schedule with status applied

  true   if now is outside every slot of that schedule

  true   if that slot's cooling_mode is dry

  false  if that slot's cooling_mode is wet

now for POST /api/telemetry is the body's ts, not the server clock. The HTTP response is exactly:

{"command": {"fan_on": false}}

Safety

The load is a 5 V USB fan. Current is limited by the USB source.

Switching is through a logic-level MOSFET on the low side of that 5 V load, with a flyback diode across the fan.

Do not write mains wiring steps in code, comments, READMEs, or diagrams.

firmware/[README.md](http://README.md) contains this sentence: Safety: 5V USB fan only. Do not connect this board to mains wiring.

Default pin map

Used when /docs/hardware.txt is missing. firmware/config.example.h is committed. firmware/config.h is gitignored.

TODO(human): confirm or replace the board and pin map from /docs/hardware.txt.

Function

GPIO

MOSFET gate for the 5 V fan

26

INA219 SDA

21

INA219 SCL

22

DHT22 data

4

Onboard LED

2

HARDWARE_SENSORS in config.h defaults to 0. When it is 0, power and temperature are the simulator formulas below and the fan GPIO is still driven. When it is 1, read the INA219 (watts) and the DHT22 (°C) using the libraries named in /docs/hardware.txt.

config.example.h:

#define WIFI_SSID "your-ssid"

#define WIFI_PASSWORD "your-password"

#define BACKEND_URL "[http://192.168.1.50:8000](http://192.168.1.50:8000)"

#define DEVICE_ID "esp32-fan-01"

#define HARDWARE_SENSORS 0

#define PIN_FAN 26

#define PIN_SDA 21

#define PIN_SCL 22

#define PIN_DHT 4

#define PIN_LED 2

Firmware loop

Serial 115200.

Wi-Fi reconnect every 5 seconds.

Time from NTP (configTime with server [pool.ntp.org](http://pool.ntp.org)). Do not POST until the clock is synced. Retry NTP every 30 seconds.

Every 2 seconds, POST Telemetry to {BACKEND_URL}/api/telemetry with simulated: false, Content-Type: application/json, and a 5-second HTTP timeout.

Apply [command.fan](http://command.fan)_on. Ignore a command that would flip the pin sooner than 5 seconds after the previous flip.

If no POST has succeeded for 30 seconds, force the fan ON immediately (the 5-second debounce does not block this), blink GPIO 2 at 5 Hz, and keep posting. When a POST succeeds, stop the fail-safe and honor commands again, including the debounce.

LED: blinking while Wi-Fi is down, solid when a POST succeeded within the last 30 seconds, 5 Hz blink in fail-safe.

No delay() longer than 100 ms. Use millis() for the 2-second, 5-second, and 30-second timers.

HTTP, not HTTPS, when BACKEND_URL starts with http://.

Simulator

backend/[simulator.py](http://simulator.py) runs only when START_SIMULATOR=1. It calls the in-process telemetry function every 2.0 seconds. It does not open a socket.

device_id: esp32-fan-sim

simulated: true

Initial temp_c: 32.0

Initial assumed fan_on: true

After each response, if [command.fan](http://command.fan)_on is true: temp_c = max(28.0, temp_c - 0.3) and power_w = 4.5

If false: temp_c = min(45.0, temp_c + 0.3) and power_w = 0.0

firmware/tools/fake_[esp32.py](http://esp32.py) does the same POST over HTTP to BACKEND_URL so the route can be tested without a board. Tests set START_SIMULATOR=0.

10. Photon SMS approval

States

Resting statuses: proposed, pending_approval, applied, rejected, expired, superseded.

approved is written on the row and logged, then the same function sets applied before it returns. API responses from the approve path and from a YES reply have status: applied.

proposed --request_approval, shifted_job_count > 0--> pending_approval

proposed --request_approval, shifted_job_count == 0--> applied

proposed --approve_and_apply--> applied

proposed --reject--> rejected

pending_approval --YES or approve_and_apply--> applied

pending_approval --NO or reject--> rejected

pending_approval --timeout--> expired

applied --a newer schedule is applied--> superseded

When a schedule enters pending_approval, any other pending_approval row becomes expired with reason superseded_by_new_request. When a schedule becomes applied, the previous applied row becomes superseded with replaced_by set to the new id. The baseline row is that previous applied schedule on a fresh database.

Illegal transitions return HTTP 409 and write nothing.

Every transition calls write_log with the actor argument. YES uses actor photon and via sms. The dashboard Approve button uses actor dashboard and via dashboard. NO uses reason sms_no. The Reject button uses reason dashboard.

Timeout: PHOTON_TIMEOUT_SECONDS default 300. A background task, not time.sleep inside the request, checks the pending id. If that row is still pending_approval at the deadline, call expire with actor photon and reason timeout. The applied schedule is left in place.

shifted_job_count > 0 is the only condition that requires a person. The slider's POST /api/optimize does not request approval.

SMS text

send_approval_sms sends exactly this string, with shifted_kwh formatted to one decimal:

GridPulse: {shifted_job_count} jobs shifted, {shifted_kwh:.1f} kWh moved into {start}-{end} UTC. Reply YES or NO

start is the earliest slot ts where a shifted job's optimized fraction exceeds its baseline fraction. end is one hour after the latest such slot ts. Both are YYYY-MM-DDTHH:MM:SSZ.

Reply parsing

Normalize reply text with strip().upper(). Accept only the exact strings YES and NO.

YES: approve_and_apply on the single pending_approval schedule.

NO: reject on that schedule.

Any other text: if this schedule has not yet had a clarification, send the text Reply YES or NO, log clarification_sent, and leave the status pending_approval. A second non-matching text is logged as sms_reply and does not send another SMS.

The pending schedule is the only row with status pending_approval. Zero such rows produces WebhookResult ignored / not_pending.

Duplicate message_id values produce ignored / duplicate and do not change status. Remember message ids in memory and in the decision log.

What is our webhook versus Photon's API

Mock mode (PHOTON_MODE=mock, the default) accepts this body at POST /api/webhooks/photon and does not call Photon:

{"message_id": "sim-001", "from_number": "+15551230000", "text": "YES"}

scripts/simulate_[reply.py](http://reply.py) takes one argument, YES or NO, and posts that body with a new message_id of the form sim- plus 8 hex chars. PHOTON_MODE=mock performs no network I/O.

Live mode maps Photon's JSON onto message_id, from_number, and text, then uses the same state machine.

TODO(human): Photon send-message URL, headers, request JSON, webhook JSON field names, and signature or token check from /docs/photon.txt.

Until that mapping is in /docs/photon.txt, PHOTON_MODE=live logs error with integration photon, returns HTTP 501 photon_unconfigured from the webhook, and send_approval_sms returns mock-sms- + schedule_id without networking. The dashboard Approve button still applies the schedule.

If the docs name a signature or token, the live webhook checks it and returns 401 on failure. If they do not, the live webhook accepts only from_number equal to OPERATOR_PHONE and records that limit in docs/[DECISIONS.md](http://DECISIONS.md).

Outbound send timeout is 10 seconds, then one retry, then log error and leave the schedule pending_approval.

11. Gemini explain()

explain(schedule, signals, prev_schedule) -> str

prev_schedule is the schedule that was applied before this one, or null.

Build this summary object and send only this object. Do not send raw logs, phone numbers, or secrets.

{

  "alpha": 0.5,

  "shifted_jobs": [

    {"job_id": "job-cp-01", "from_hours": [0, 1, 2, 3], "to_hours": [10, 11, 12, 13]}

  ],

  "drivers": [

    {"name": "curtailment_mw", "hour": 10, "value": 250.0},

    {"name": "marginal_gco2_per_kwh", "hour": 18, "value": 420.0}

  ],

  "cooling_dry_hours": [],

  "savings_pct": {"cost": 11.4, "carbon": 13.3, "water": 10.0},

  "metrics": {"cost_usd": 12.4, "carbon_kg": 18.2, "water_l": 90.0, "energy_kwh": 110.0}

}

from_hours / to_hours are ascending slot indexes where that schedule's fraction is > 0. Include only shifted jobs.

Driver 1: the slot with the largest curtailment_mw. Lowest t wins ties.

Driver 2: the slot with the largest marginal_gco2_per_kwh, skipping driver 1's slot if it would repeat. If it still repeats, use the slot with the largest price_usd_per_mwh other than driver 1.

cooling_dry_hours is the ascending list of t whose cooling_mode is dry.

Instruction string sent with the summary: Write 2 or 3 plain sentences. Mention the carbon versus water trade-off at this alpha. Use only numbers that appear in the summary. Do not use markdown.

Timeout 6 seconds, then one retry. Cache key is schedule_id + ":" + format(alpha, ".2f"). On a cache hit, return the stored text and do not call the network. Also store the text on schedules.explanation.

Number guard: extract every number matching -?\d+(\.\d+)? from the model text. Each one must be within 0.05 absolute of some number in the summary JSON. If any number fails, drop the model text and use the template.

Template, used for mock mode, timeout, guard failure, and an empty model body:

Simulated result at alpha {alpha:.2f}: this schedule costs ${cost_usd:.2f}, emits {carbon_kg:.2f} kg CO2, and uses {water_l:.1f} L of water, which is {cost_pct:+.1f}% cost, {carbon_pct:+.1f}% carbon, and {water_pct:+.1f}% water versus the naive baseline. Jobs moved: {shifted_job_count}. Cooling follows the wet/dry split in the schedule.

cost_pct is savings_pct.cost, and the same for carbon and water.

GET /api/explain/{schedule_id} calls explain, writes event explanation with actor gemini, and returns ExplainResponse. GEMINI_MODE=mock returns the template and source fallback without a network call. A cache hit returns source cache.

TODO(human): Gemini client constructor, model id, and request shape from /docs/gemini.txt. Put the model id in GEMINI_MODEL. If GEMINI_MODE=live and GEMINI_MODEL is empty or the docs file is missing, use the template and log error. Do not guess a model name.

12. Agent envelope and negotiation

JSON envelope. The key is from, even though it is a Python keyword. The Pydantic field is from_ with alias from, and serialization uses the alias.

Field

Type

Rule

msg_id

string

msg- plus 12 hex chars

from

string

grid-agent, dc-agent, ev-agent, or bridge

to

string

same set

type

string

inform, propose, accept, or counter

schedule_id

string

body

object

One of the bodies below

{

  "msg_id": "msg-0123456789ab",

  "from": "dc-agent",

  "to": "bridge",

  "type": "counter",

  "schedule_id": "sch-20260621T190000Z-a050",

  "body": {"constraint": "max_it_kw", "max_it_kw": 6.0, "reason": "dc thermal limit"}

}

Bodies:

inform: {"surplus_start": string or null, "surplus_end": string or null, "curtailment_mw_min": number}

propose: {"schedule": <Schedule>}

accept: {"accepted": true}

counter from dc-agent: {"constraint": "max_it_kw", "max_it_kw": number, "reason": "dc thermal limit"}

counter from ev-agent: {"constraint": "ev_deadline", "job_id": string, "deadline_ts": string, "reason": "minimum charge deadline"}

A malformed envelope is logged as error with integration agents and is not executed.

Flow

negotiate(schedule) does this and never raises. Wall clock limit 8 seconds. On timeout or any exception, log error and return the input schedule unchanged.

grid-agent sends inform to bridge. curtailment_mw_min is the number CURTAILMENT_SURPLUS_MW (default 50). surplus_start is the ts of the first slot with curtailment_mw >= CURTAILMENT_SURPLUS_MW. surplus_end is one hour after the last such slot. If no slot qualifies, both bounds are null.

Round 1: bridge sends propose to dc-agent and to ev-agent.

dc-agent replies counter with max_it_kw equal to DC_MAX_IT_KW (default 6.0) when any slot has it_load_kw > DC_MAX_IT_KW. Otherwise it replies accept.

ev-agent replies counter when an ev_charge job has fraction > 0 in a slot with ts >= EV_FORCE_DEADLINE. deadline_ts in the body is EV_FORCE_DEADLINE. Otherwise it replies accept.

If every reply is accept, return the schedule.

If any reply is counter, merge constraints: max_it_kw is the smallest such value, and job_deadlines[job_id] is the earliest deadline named for that job. Call optimize once with those constraints and the schedule's alpha. If the result is OptimizeError, return the input schedule.

Round 2: propose the new schedule once. Record the replies. Do not call optimize again. Return the round-2 schedule.

Each envelope is one negotiation_msg log row. The payload is the envelope.

FETCHAI_MODE=local (default) uses in-process function calls. No sockets.

FETCHAI_MODE=network is allowed only for SDK calls copied from the docs.

TODO(human): [Fetch.ai](http://Fetch.ai) / uAgents / Agentverse constructor and send-message calls from /docs/fetchai.txt. If that file is missing, stay on FETCHAI_MODE=local.

python -m agents.demo_scenario builds a schedule with one slot at it_load_kw 8.0, which is above the default 6.0, and prints at least one counter envelope.

The backend calls negotiate from POST /api/demo/trigger-surplus and from request_approval, not from POST /api/optimize.

13. Environment variables

/backend loads .env from the repo root. .env.example is committed with these lines. .env is gitignored.

MODE=cached

HARDWARE_MODE=simulated

START_SIMULATOR=1

DATABASE_URL=

DATA_DIR=

OPTIMIZER_MODE=real

CORS_ORIGINS=[http://localhost:5173](http://localhost:5173)

PHOTON_MODE=mock

PHOTON_TIMEOUT_SECONDS=300

OPERATOR_PHONE=

GEMINI_MODE=mock

GEMINI_MODEL=

GEMINI_API_KEY=

SOLANA_MODE=mock

SOLANA_RPC_URL=[https://api.devnet.solana.com](https://api.devnet.solana.com)

SOLANA_KEYPAIR_PATH=

FETCHAI_MODE=local

DC_MAX_IT_KW=6.0

CURTAILMENT_SURPLUS_MW=50

EV_FORCE_DEADLINE=2026-06-21T21:00:00Z

ELEVENLABS_API_KEY=

ELEVENLABS_VOICE_ID=

Frontend .env contains only:

VITE_API_URL=[http://localhost:8000](http://localhost:8000)

DATA_DIR empty means <repo>/data. Tests set START_SIMULATOR=0.

GEMINI_MODEL and GEMINI_API_KEY are read by our process. How they are passed into the SDK is determined by the Gemini docs, not by a guessed constructor.

TODO(human): any Photon credential variable names beyond OPERATOR_PHONE from /docs/photon.txt. Do not add those names until the file lists them.

TODO(human): ElevenLabs request URL, voice-id field, and response audio format from /docs/elevenlabs.txt.

ESP32 BACKEND_URL lives in firmware/config.h, not in this env file.

14. Solana devnet logging

record_settlement(schedule) runs only after the schedule row has been committed with status=applied. The HTTP handler starts it as a background task and returns the applied schedule without waiting.

The memo is one JSON object, keys sorted, compact separators, placed in an SPL Memo instruction:

{"carbon_saved_kg":0.0,"gridpulse":1,"hash":"<metrics_hash of schedule.metrics>","schedule_id":"sch-20260621T190000Z-a050"}

carbon_saved_kg is round(baseline_metrics.carbon_kg - metrics.carbon_kg, 6). gridpulse is the integer 1.

Sign with the keypair file at SOLANA_KEYPAIR_PATH. Send to SOLANA_RPC_URL. Timeout 10 seconds. No retry. On failure, log error with integration solana and return None. The applied schedule stays applied.

On success, log settlement_tx with actor solana, mode live, the signature string, and explorer_url [https://explorer.solana.com/tx/{signature}?cluster=devnet](https://explorer.solana.com/tx/{signature}?cluster=devnet).

SOLANA_MODE=mock does not open a socket. It returns mocksig- plus the first 16 hex characters of SHA-256 of the UTF-8 schedule_id, and logs settlement_tx with that signature, explorer_url null, and mode mock.

Library calls are taken from the installed solders or solana package source. Do not invent method names. scripts/solana_[setup.md](http://setup.md) states that this is an audit log of simulated curtailment events on devnet, and that no production token and no real money are involved.

15. Frontend panels

One dark page. src/api/types.ts uses these JSON names, including snake_case. The only backend base URL is VITE_API_URL. Mock fixtures in src/mock/ validate against the same types.

If the health request fails, show the banner text Backend unreachable. Showing mock data. and render the fixtures.

Layout, top to bottom:

Header. Badge text is the health mode (cached or live) and the health hardware_mode (real or simulated). Next to the KPIs, the visible string SIMULATED SAVINGS.

Three KPI cards from the schedule returned by POST /api/optimize (or the mock): savings percent and absolute delta for cost (USD), carbon (kg), and water (L). Absolute delta is baseline_metrics minus metrics for cost_usd, carbon_kg, and water_l.

Slider alpha from 0 to 1. Left label Favor carbon. Right label Favor water. Display alpha with two decimals. Debounce 250 ms, then POST /api/optimize. Redraw from that response. The redraw does not wait for approval.

Gemini card. Text from GET /api/explain/{schedule_id} for the schedule on screen.

24-hour timeline. One row per job that has a fraction > 0, blocks where it runs. A strip of cooling_mode per hour. A separate mark on hours whose signal curtailment_mw >= 50.

Signals chart with three series: price_usd_per_mwh, marginal_gco2_per_kwh, curtailment_mw.

Telemetry chart for GET /api/telemetry?minutes=5: power_w and temp_c, and a mark where fan_on is true.

Decision log, ascending time, actor name, event name, relative timestamp. Use GET /api/stream when the first event arrives within 2 seconds of connecting. Otherwise poll GET /api/decisions?after={last_log_id} every 2 seconds. When event is settlement_tx and payload.explorer_url is a string, show that URL.

Action bar for the on-screen schedule. Request Approval is enabled only for proposed and calls POST /api/schedules/{id}/request-approval. Approve is enabled for proposed and pending_approval and calls POST /api/schedules/{id}/approve. Reject is enabled for those same two statuses and calls POST /api/schedules/{id}/reject. Show status as text.

A collapsed panel with buttons Trigger Surplus (POST /api/demo/trigger-surplus) and Reset (POST /api/demo/reset).

Each panel has a loading state and an error state. No request goes anywhere except VITE_API_URL.

16. Acceptance tests

Savings assertions use the shared metrics functions. Tests call the real solver except where a test name says the HTTP client is in mock mode.

Data (C1)

DATA-1. signals_cached.csv has 48 data rows, no empty fields, and timestamps exactly 1 hour apart starting at 2026-06-21T07:00:00Z.

DATA-2. Row 0 matches local hour 0 in section 5.1. Row 10 matches local hour 10. The sum of water_stress_index on rows 0..23 is 17.28.

DATA-3. jobs.json and assets.json equal the JSON in sections 5.2 and 5.3, and they parse with the Pydantic models.

DATA-4. Importing the loader and reading the CSV performs no network I/O.

Optimizer (C2)

OPT-1. On the sample, every job's fractions sum to duration_h and are 0 outside its window.

OPT-2. Every slot has it_load_kw <= 20 and ev_load_kw <= 50.

OPT-3. At alpha=0, optimized carbon_kg <= baseline carbon_kg.

OPT-4. At alpha=1, optimized water_l <= baseline water_l.

OPT-5. Each non-checkpointable job is one contiguous block of fraction 1.

OPT-6. For alpha in 0, 0.25, 0.5, 0.75, 1 on the sample, carbon_kg is non-decreasing and water_l is non-increasing, with an absolute tolerance of 0.05.

OPT-7. A job with duration_h 30 returns OptimizeError infeasible and that job_id, and does not raise.

OPT-8. optimize on the sample returns in under 2 seconds.

OPT-9. savings_pct(m, m) is all zeros. savings_pct when a baseline component is 0 yields 0 for that component and does not raise.

Backend (D1)

API-1. Each route in section 6 returns a body that parses as the model named there.

API-2. POST /api/telemetry with the section 5.6 example returns [command.fan](http://command.fan)_on equal to the section 9 rule for the applied schedule.

API-3. A telemetry body with power_w 900 is stored flagged, appears in a telemetry_flagged log, and is absent from GET /api/telemetry.

API-4. With MODE=cached, START_SIMULATOR=0, empty DATABASE_URL, and no network, the app starts and GET /api/health reports database sqlite.

API-5. An extra JSON key on POST /api/optimize returns 422 validation_error.

Photon (D3)

PH-1. Mock webhook YES moves pending_approval to applied and supersedes the previous applied row.

PH-2. NO sets rejected and leaves the previous applied row applied.

PH-3. Text MAYBE sends one clarification. A second MAYBE does not send another.

PH-4. The same message_id twice does not apply twice.

PH-5. After PHOTON_TIMEOUT_SECONDS, the pending row is expired and the applied row is unchanged. The test may set the timeout to 1 second.

PH-6. PHOTON_MODE=mock opens no socket. Logs contain the masked phone, not OPERATOR_PHONE.

Gemini (D4)

GEM-1. A client timeout returns the section 11 template.

GEM-2. Model text that contains the number 99999 is discarded and the template is returned.

GEM-3. Two explains with the same schedule_id and alpha call the client once.

GEM-4. The returned text contains at most 3 period characters.

Firmware (C3)

FW-1. fake_[esp32.py](http://esp32.py) posts a body that parses as Telemetry and applies [command.fan](http://command.fan)_on.

FW-2. The firmware source contains no delay( call with a literal greater than 100, and the README contains the section 9 safety sentence.

Agents (D5)

AG-1. A schedule whose IT load is at most DC_MAX_IT_KW and whose EV fractions are all before EV_FORCE_DEADLINE gets two accept replies and is returned unchanged.

AG-2. A schedule with one slot it_load_kw 8 and default DC_MAX_IT_KW 6 produces a counter and one optimize call.

AG-3. A second round of counters does not call optimize again.

AG-4. A bridge exception returns the input schedule and writes error.

Solana (D6)

SOL-1. SOLANA_MODE=mock returns mocksig- plus 16 hex chars and does not open a socket.

SOL-2. The memo JSON contains schedule_id and hash equal to metrics_hash(schedule.metrics).

SOL-3. A settlement timeout still leaves the schedule applied.

Frontend (D2)

FE-1. Moving the slider queues one POST /api/optimize after 250 ms, not one call per pointer event.

FE-2. KPI text includes the fixture percents and the string SIMULATED SAVINGS.

FE-3. A new decision-log fixture appears in the feed.

End to end

backend/tests/test_[e2e.py](http://e2e.py), MODE=cached, HARDWARE_MODE=simulated, START_SIMULATOR=0, PHOTON_MODE=mock, GEMINI_MODE=mock, SOLANA_MODE=mock, FETCHAI_MODE=local, empty DATABASE_URL:

E2E-1. GET /api/health is 200 with mode cached, hardware_mode simulated, database sqlite.

E2E-2. GET /api/jobs returns 8 jobs.

E2E-3. POST /api/optimize with {"alpha": 0} returns schedule_kind optimized and metrics.carbon_kg <= baseline_metrics.carbon_kg.

E2E-4. POST /api/demo/reset, then POST /api/demo/trigger-surplus, returns within 3 seconds with shifted_job_count >= 1, status pending_approval, and savings_label simulated. GET /api/decisions includes event proposed.

E2E-5. POST /api/webhooks/photon with {"message_id":"sim-e2e0001","from_number":"+15551230000","text":"YES"} returns status applied.

E2E-6. POST /api/telemetry with device_id esp32-fan-sim, a current ts inside the horizon, power_w 4.5, temp_c 30, fan_on false, simulated true, returns [command.fan](http://command.fan)_on matching section 9 for that applied schedule.

E2E-7. GET /api/explain/{that schedule_id} returns text whose length is greater than 0 and source fallback.

17. Agent task prompt template

Copy this block, replace the angle-bracket fields, and paste it as the whole task.

Read [SPEC.md](http://SPEC.md) fully before starting. If this prompt and [SPEC.md](http://SPEC.md) disagree, follow [SPEC.md](http://SPEC.md) and record the disagreement in docs/SPEC_[CHANGES.md](http://CHANGES.md).

Task: <one paragraph>

You may edit only: <paths>

Deliverables:

1. <file or behavior, naming SPEC section numbers>

2. <tests that assert the SPEC section 16 ids: ...>

Constraints:

- Do not rename JSON fields, status strings, or env vars from [SPEC.md](http://SPEC.md).

- Do not invent sponsor API URLs, headers, or SDK calls. If /docs/<file>.txt is missing the shape you need, stop and list the question in the PR. Use the mock mode from [SPEC.md](http://SPEC.md) meanwhile.

- External calls have a timeout and at most one retry, then a decision-log event "error" and the SPEC fallback.

- No API keys or phone numbers in code or logs.

Branch: <feat/name or fix/name>. Do not commit to main.

PR: summary, exact commands you ran, test output pasted from the run, assumptions, and any SPEC change proposal.

18. Lead checklist before launching agents

[SPEC.md](http://SPEC.md) is committed at the repo root.

.env.example matches section 13. .env exists locally, is gitignored, and contains no production keys. Mock modes are the values in section 13.

Empty append-only files exist: docs/[DECISIONS.md](http://DECISIONS.md), docs/[PROGRESS.md](http://PROGRESS.md), docs/SPEC_[CHANGES.md](http://CHANGES.md).

These files exist before the agent that needs them is launched. A file may be a stub that only names the missing fact. docs/photon.txt, docs/tigerdata.txt, docs/gemini.txt, docs/fetchai.txt, docs/elevenlabs.txt, docs/hardware.txt, docs/data_sources.txt.

TODO(human) lines in this spec are either filled or the dependent agent is still on the mock path.

Launch order is the table in [PROMPTS.md](http://PROMPTS.md): data and optimizer and backend and frontend first, then Photon and firmware and Gemini, then the integration fixer. [Fetch.ai](http://Fetch.ai) and ElevenLabs only after E2E-1 through E2E-7 pass. Solana and Vultr only after that.

Each agent has a branch feat/<component>-<task>. main is protected by not giving agents permission to push to it.

The first merge order is backend, optimizer, frontend, then Photon, Gemini, firmware. Agents touch only the paths in section 2.

A phone for Photon is available, or PHOTON_MODE stays mock and the demo uses scripts/simulate_[reply.py](http://reply.py) plus the Approve button.

The ESP32 demo uses the 5 V fan only. The pin map is either the section 9 default or a filled docs/hardware.txt.

The judge script calls savings "simulated" and does not claim live CAISO, live water data, real money, or a production token.

