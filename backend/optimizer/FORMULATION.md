# How the scheduler decides

GridPulse looks at one day, split into 24 hours. It has a list of compute jobs and EV charges. Each job needs a fixed number of hours at a fixed power, and it may only run between its release time and its deadline. The scheduler answers two questions:

1. In which hours does each job run?
2. In each hour, how many kilowatts of data-center IT load are cooled by the wet tower, and how many by the dry cooler?

EV charging sits on the same clock. It is not cooled.

## Jobs

A checkpointable job can pause and resume. For each allowed hour the solver picks a fraction x between 0 and 1. The fractions add up to the job's duration. 1 means full power for that hour. A fraction below 1 is how a job with a non-integer duration finishes its last hour.

A non-checkpointable job cannot pause. It has to run at full power for consecutive hours. The solver picks exactly one start hour, using a yes/no variable for each hour where a block of that length still fits in the window. The job is then on for `duration` hours from that start and off everywhere else.

## Why wet and dry are two numbers

Wet cooling spends 0.15 kW of extra electricity per kW of IT, and it uses water. Dry cooling spends 0.35 kW of extra electricity per kW of IT, and it uses no water. The IT load in an hour is split into two piles that add up to the whole load:

- yw is the IT kilowatts served by wet cooling
- yd is the IT kilowatts served by dry cooling
- yw + yd = IT load

They are separate so electricity and water stay straight-line formulas. One on/off "cooling mode" multiplied by the IT load would be a product of two unknowns, and this solver cannot handle that product. With yw and yd, extra electricity is `0.15 * yw + 0.35 * yd`, and water depends only on yw.

An hour with no IT load has both piles at zero. The label is still wet, because dry is used only when yd is larger than yw, and that hour uses no water.

Water for the day, in liters, is:

`1.8 * yw * water_stress_index`, summed over the 24 hours

1.8 is liters of water per kWh of IT on wet cooling, before stress. The stress index (about 0.68 to 0.76 in the sample) makes the same wet kilowatt cost more water in a drier hour. Dry kilowatts add zero water. Because the objective is a straight line, an hour is never better as a mix than as all-wet or all-dry. The published mode is dry when yd is larger than yw, and wet otherwise.

Site power in an hour, in kW, is:

`IT + 0.15 * yw + 0.35 * yd + EV`

One kW held for one hour is 1 kWh. Dollars are `kW * price_per_MWh / 1000`. Carbon kilograms are `kW * grams_CO2_per_kWh / 1000`.

## What we minimize

The naive schedule starts every job in the first hour it is allowed to run, keeps it on until it finishes, and cools every IT kilowatt with the wet tower. That schedule has a cost, a carbon mass, and a water volume. Call those the baselines.

The optimized schedule minimizes:

`0.3 * (cost / cost_baseline) + (1 - alpha) * (carbon / carbon_baseline) + alpha * (water / water_baseline)`

Alpha is the slider, from 0 to 1.

- Alpha 0 ignores water. The solver goes after carbon, and it always keeps a 30% weight on the electricity bill.
- Alpha 1 ignores carbon. The solver goes after water. Dry cooling becomes attractive because it zeroes that hour's water, at the cost of more electricity. On the committed sample this drives water to zero: every IT kilowatt is dry-cooled. That is the objective at work, not a separate cap.
- Dividing by the naive schedule puts dollars, kilograms, and liters on one scale. If a baseline number is 0, that term is dropped, so we never divide by zero.

Alpha only changes those three weights. It is not multiplied by a decision variable inside the model.

## Limits, and a job that cannot fit

Each job's fractions add up to its duration, and they are 0 outside its window. IT load stays at or below the data-center capacity (20 kW in the sample). EV load stays at or below the charger capacity (50 kW). An optional cap can set a lower IT limit, and an optional deadline can only move a job's deadline earlier.

If a job's window has fewer hours than it needs, or a non-checkpointable job has nowhere to place a contiguous block, we do not run the solver. We return an error that names the job: `job {id} cannot complete inside its window`. A failed solve returns an error with no job id. Neither case raises.

## One shared scoreboard

Cost, carbon, water, and energy are computed by one function for both schedules. Percent savings is `(baseline - optimized) / baseline * 100` for each of cost, carbon, and water, in one function. Positive means the optimized schedule is lower. Every savings figure is simulated.

The whole model is one mixed-integer linear program, solved with HiGHS (`scipy.optimize.milp`). Checkpointable fractions are continuous. Start markers are binary. The time limit is 1.5 seconds. The same inputs always produce the same hours and the same metrics.
