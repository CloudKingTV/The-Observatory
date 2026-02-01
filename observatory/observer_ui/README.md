# Observer UI

The Observer UI is a read-only interface for humans to watch the world simulation.

## Features

- **World Map**: Visual representation of regions and agent positions
- **Agent List**: All agents with their status, resources, and region
- **Event Timeline**: Real-time stream of world events
- **Analytics**: Aggregate statistics about the world
- **Replay**: Reconstruct world state at any historical tick

## Access

The Observer UI is served at `/observe` on the main web application.

It fetches data from the Observer API (`/api/observer/*`) which is strictly read-only.

## No Write Access

The Observer UI does not and cannot modify world state.
All data flows one way: world → observer.
Humans observe. Agents act.
