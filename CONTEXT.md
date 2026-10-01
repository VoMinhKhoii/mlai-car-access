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
The current estimate of a segment's Clear Width, as a minimum and a maximum in metres set by its Evidence.
_Avoid_: width estimate, predicted width

**Alley Label**:
The familiar Vietnamese name shown for a Width Range: hẻm xe máy, hẻm ba gác, hẻm xe hơi, or ô tô tránh.
_Avoid_: alley class, alley type

**Evidence**:
One sourced, dated observation that sets a minimum or maximum on a Width Range or supports another check, such as a Way Out.
_Avoid_: data point, signal, label

**Evidence Tier**:
How much a source is trusted, strongest first: Measured, Official, Observed, Declared, Inferred. A higher tier sets the range; lower tiers may only narrow it.
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
A place the vehicle can get into, stop at for its Stop Intent, and get back out of; the destination door is the best possible Stop Point.
_Avoid_: parking spot, handoff point, drop point

**Stop Intent**:
Whether the vehicle will be left there (Park, *đỗ xe*) or stop briefly with the driver aboard to let people or goods on or off (Pickup/Drop-off, *dừng xe*). The Vietnamese terms match the legal split between đỗ and dừng.
_Avoid_: trip type, mode

**Way Out**:
How a vehicle leaves a Stop Point using only alleys it fits: drive through, turn around, or reverse to a turning space.
_Avoid_: exit, egress

**Reverse Limit**:
The longest reversing distance that still counts as a normal Way Out; a Stop Point needing more has a tight exit.
_Avoid_: max backup

**Fit Network**:
The part of the road and alley network that one specific vehicle fits.
_Avoid_: drivable graph, car network

**Walk Leg**:
The on-foot path between a Stop Point and the destination door.
_Avoid_: last mile, remaining distance

**Hard Check**:
A pass/fail test every Stop Point must pass to be offered: route in on the Fit Network, a Way Out, flood within the wading limit, Stop Legality, and a Walk Leg under its cap.
_Avoid_: constraint, filter

**Unverified**:
Said of an alley or Stop Point with no evidence either way on a check; it is kept, but ranked after every verified option.
_Avoid_: low risk, safe, unknown risk

### Flood

**Dwell Window**:
The time from arrival until the vehicle leaves a Stop Point; the flood check covers the route in, the Stop Point and the Way Out across it.
_Avoid_: trip time, parking duration

**Depth Range**:
The expected minimum and maximum water depth on a segment during a Dwell Window, from tide, rain and that street's flood history.
_Avoid_: flood level, predicted depth

**Safe Water Depth**:
The deepest still water a specific vehicle should drive through, part of its Vehicle Profile.
_Avoid_: wading depth (the manufacturer's figure is only one input), ground clearance

**Flood Status**:
A segment's verdict for one vehicle and Dwell Window: passable, risky (treated as Unverified), or blocked.
_Avoid_: flood risk, flood score

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
