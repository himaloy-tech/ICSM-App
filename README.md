# Quadfit

## Elevator pitch

**Quadfit makes fitness easier to plan—and easier to stick with.** It brings workout scheduling, activity tracking, and calorie logging into one simple, mobile-friendly dashboard. Users can plan sessions, track completed workouts, and manage their meals in a few clicks. Whether you’re building a new routine or staying consistent, Quadfit helps turn your fitness goals into daily action.

## About the website

Responsive fitness dashboard built with HTML, CSS, and vanilla JavaScript. For the basic tracker, open `index.html` in a browser. No build step or dependencies are required.

Includes dashboard, month navigation and day selection, workout completion, meal logging and removal, daily calorie targets, profile preferences, weekly workout progress, and mobile navigation. Progress is stored in the browser's local storage. Meals start empty so the daily total only reflects items you log.

### Meal photo estimates and activity sync

Copy `.env.example` to `.env`, add an OpenAI API key if you want photo estimates, then run the included Python standard-library server:

```sh
cp .env.example .env
# Add credentials to .env using a local editor; .env is ignored by Git.
python3 server.py
```

Then open <http://127.0.0.1:8000>. Photo estimates use the OpenAI API and require an API key with billing enabled; image requests may incur API charges. Quadfit sends the compressed meal image for analysis and saves only the reviewed meal name and calories in browser storage. Without an API key, manual meal entry remains available.

To enable Strava, create a Strava API application and add its client ID and secret to `.env`. Set `STRAVA_REDIRECT_URI` to `http://localhost:8000/api/strava/callback`.

Set the Strava application's callback domain to `localhost` and its redirect URI to the value above. The app requests permission to read the connected athlete's activities, refreshes tokens on the server, and syncs today's available activity calorie values. Strava currently requires a Strava subscription to create an API application. OAuth tokens stay in the local server's memory and are cleared when it stops; the server binds to localhost and is intended for the local single-user app.

Nike Run Club does not connect directly to this browser app. Nike supports syncing NRC workouts to Strava; connect those apps in Nike Run Club, then connect Strava to Quadfit. See [Nike and Strava setup](https://support.strava.com/en-us/articles/15401850-nike-and-strava).

The burned calorie total can also be entered manually. Both meal and exercise calorie values are estimates and can vary by portion size, device, and method.

The hero uses a still gym photograph rather than video; replace the hero background with your own licensed video when available. Photography loads from Unsplash and fonts from Google Fonts; system fonts and a dark background provide fallbacks without internet.

Personal scheduler: select a calendar date, then use “Schedule a workout” to add a named session, time, and duration. Use the check, pencil, or remove controls to complete, edit, or delete it. The active minutes card opens the weekly activity log. Metrics now use actual completed sessions rather than sample totals. Existing Defiant browser data migrates automatically.
