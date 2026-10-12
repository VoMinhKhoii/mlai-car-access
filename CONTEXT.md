# Car Access Layer

A map layer for Vietnamese cities that tells a driver whether their specific vehicle can reach an address inside the alley network (hẻm/ngõ) and get back out, and if not, where to stop and how far the rest is on foot.

## Language

### People

**Private Driver**:
A person driving their own car to a destination who must leave the car somewhere and walk the rest.
_Avoid_: user, car owner, B2C

**Ride-hailing Driver**:
A car-hailing driver (Xanh SM, Grab Car, Be Car) who stops only briefly to pick up or drop off a passenger and stays with the car.
_Avoid_: taxi driver, Grab driver, B2B

**Delivery Driver**:
A van or light-truck driver who stops to unload goods; a secondary persona in the large-vehicle size group.
_Avoid_: shipper, logistics user

**Emergency Vehicle**:
A fire truck or ambulance that needs to reach an address; a deferred persona in the large-vehicle size group.
_Avoid_: rescue vehicle

### Arrival

**Arrival Plan**:
The answer for one destination, one vehicle and one Stop Intent: up to three ranked Stop Points, each with a route in that avoids alleys the vehicle doesn't fit.
_Avoid_: result, recommendation

**Verdict**:
The one-line headline of an Arrival Plan: the vehicle can reach the door, must stop elsewhere, or the evidence is insufficient to say.
_Avoid_: score, rating

**Alley Fit**:
How well a specific vehicle fits one alley segment: fits, tight, doesn't fit, or unknown.
_Avoid_: accessibility, width score

### Access evidence

**Clear Width**:
The narrowest width a vehicle can actually use along an alley segment, after fixed encroachments such as steps, ramps and planters.
_Avoid_: alley width, road width, lộ giới

**Width Range**:
The evidence-based minimum and maximum estimates for one segment; a numeric range alone does not prove usable Clear Width.
_Avoid_: width score, verified width

**Width Basis**:
What the width value represents: physical clear width, parcel-gap estimate, road-width estimate, declared width, or an inference.
_Avoid_: source tier, confidence

**Longitudinal Coverage**:
Whether width evidence reaches both segment endpoints, its maximum sample spacing, and whether sampling was truncated.
_Avoid_: sample count alone

**Decisive Clearance**:
Physical measured or observed Clear Width with stated uncertainty, complete endpoint coverage, and no evidence conflict.
_Avoid_: inferred fit, parcel width

**Alley Label**:
The familiar Vietnamese name shown for a Width Range: hẻm xe máy, hẻm ba gác, hẻm xe hơi, or ô tô tránh.
_Avoid_: alley class, alley type

**Evidence**:
One sourced, dated observation that sets a minimum or maximum on a Width Range or supports another check, such as a Way Out.
_Avoid_: data point, signal, label

**Evidence Tier**:
Trust classification for evidence source, strongest first: Measured, Official, Observed, Declared, Inferred. Consistent higher-tier evidence controls the range; lower tiers may narrow it. This is distinct from Width Basis: official source provenance does not make an inferred parcel gap a measured clear width.
_Avoid_: confidence level, weight, priority

### Vehicles

**Vehicle Profile**:
The physical limits reasoned about for one vehicle: width including mirrors, length, turning radius, ground clearance, wading depth and powertrain.
_Avoid_: car settings, vehicle config

**Size Class**:
A coarse vehicle group (mini, sedan, crossover, 7-seat SUV/MPV, van, light truck) that yields an approximate Vehicle Profile when no exact model is chosen.
_Avoid_: vehicle type, category

**Vehicle Model**:
A specific make and model from the catalogue of popular Vietnamese vehicles, whose published specs yield a precise Vehicle Profile.
_Avoid_: car, variant

**Linked Vehicle**:
A vehicle identified through the driver's VETC account rather than chosen by hand.
_Avoid_: synced car, VETC car

**Stop Point**:
A candidate location evaluated for route-in, Stop Legality, Walk Leg, and Way Out; some checks may remain explicitly unverified.
_Avoid_: guaranteed parking spot, handoff point, drop point

**Stop Intent**:
Whether the vehicle will be left there (Park, *đỗ xe*) or stop briefly with the driver aboard to let people or goods on or off (Pickup/Drop-off, *dừng xe*). The Vietnamese terms match the legal split between đỗ and dừng.
_Avoid_: trip type, mode

**Way Out**:
How a vehicle may leave a Stop Point, with direction and confidence; turns or parking-lot gates without maneuver evidence remain unverified.
_Avoid_: guaranteed exit

**Reverse Limit**:
The longest reversing distance that still counts as a normal Way Out; a Stop Point needing more has a tight exit.
_Avoid_: max backup

**Fit Network**:
The part of the road and alley network that one specific vehicle fits.
_Avoid_: drivable graph, car network

**Walk Leg**:
The mapped walking path and any separate, possibly unverified connection to the Stop Point or destination door.
_Avoid_: last mile, remaining distance

**Hard Check**:
A safety or legality evaluation for each Stop Point: fit network, Way Out, flood, Stop Legality, and Walk Leg. A candidate with missing evidence remains unverified rather than being called safe.
_Avoid_: constraint, filter

**Unverified**:
A check whose evidence is insufficient or conflicting to establish the result; it is not a safety or permission claim and ranks after verified options.
_Avoid_: low risk, safe, unknown risk

### Flood

**Dwell Window**:
The time from arrival until the vehicle leaves a Stop Point. Three flood checks span this window: (1) the route in is checked at the vehicle's arrival time, (2) the Stop Point is checked across the entire stay, and (3) the Way Out is checked at departure time. The per-leg assessment is owned by `backend/app/plan.py`.
_Avoid_: trip time, parking duration

**Depth Range**:
The estimated minimum and maximum water depth on a segment during a Dwell Window, from tide, rain and that street's flood history. A missing numeric Depth Range is not a verdict: it may mean no depth was estimated, or that required evidence is missing. Read the separate Flood Knowledge before interpreting it.
_Avoid_: flood level, predicted depth

**Safe Water Depth**:
The deepest still water a specific vehicle should drive through, part of its Vehicle Profile.
_Avoid_: wading depth (the manufacturer's figure is only one input), ground clearance

**Flood Status**:
A segment's verdict for one vehicle and Dwell Window: passable (known evidence supports staying within the vehicle limit), risky (the range straddles the limit, or knowledge is incomplete), or blocked (known positive evidence reaches the limit). The assessment is owned by `backend/app/flood.py`.
_Avoid_: flood risk, flood score

**Flood Knowledge**:
Whether the flood assessment rests on complete evidence or has a known gap: known (sound), missing_history (no past observations), missing_tide (tide required but unavailable), or stale_positive_observation (expired flood report with no newer valid dry observation). Implemented by `FloodAssessment` and `FloodSnapshot` in `backend/app/flood.py`.
_Avoid_: confidence, risk level

**Observation Validity**:
An observation (flood or dry report) that is within `FLOOD_REPORT_VALID_H` from its recorded time. An expired positive observation persists until a newer, still-valid dry observation arrives; absence of record is not evidence of dryness. Observation validity is owned by `FloodSnapshot` in `backend/app/flood.py`.
_Avoid_: stale data, outdated evidence

### Community

**Arrival Confirmation**:
A driver's one-tap report after arriving (got in / tight / couldn't get in), recorded as Observed Evidence for their Vehicle Profile.
_Avoid_: feedback, rating, review

**Temporary Blockage**:
A same-day obstruction in an alley, such as a wedding or funeral tent, a market or parked motorbikes, reported by drivers; it expires at the end of the day.
_Avoid_: incident, closure

**Standard Route**:
The route an ordinary car map would give, shown next to the Arrival Plan for contrast.
_Avoid_: default route, Goong route

### Rules

**Stop Legality**:
Whether the law allows this vehicle to stop or park at a place for its Stop Intent at a given time.
_Avoid_: parking rules, compliance

**Stop Rule**:
One legal constraint on stopping or parking at a place, from traffic law, a road sign or a local ordinance, possibly limited to certain days or hours; it always carries its legal citation.
_Avoid_: regulation, ban

**Permitted**:
Stop Legality where no Stop Rule forbids the Stop Intent at that place and time.
_Avoid_: legal, allowed, OK

**Restricted**:
Stop Legality where the law forbids stopping only because the roadway fits a single lane; offered for Pickup/Drop-off alone, ranked last, with the rule shown and no advice.
_Avoid_: tolerated, grey zone

**Prohibited**:
Stop Legality where a Stop Rule forbids the Stop Intent outright (signed no-stopping, crosswalk, junction, bus stop); such places are never offered.
_Avoid_: illegal, banned
