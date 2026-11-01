/**
 * Privacy policy and terms. The operator name and contact address come from the
 * server config (OPERATOR_NAME, CONTACT_EMAIL). Check every statement still matches
 * how the app is configured, and have them reviewed before a commercial launch.
 * Google's OAuth consent screen requires a public privacy policy URL.
 */
import { useEffect, useState } from "react";

export const UPDATED = "2 November 2026";

function useOperator() {
  const [op, setOp] = useState({ name: "the Breatheasy team", contact: "the contact address on this site" });
  useEffect(() => {
    fetch("/api/config")
      .then((r) => r.json())
      .then((c) => setOp({ name: c.operator_name || op.name, contact: c.contact_email || op.contact }))
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return op;
}

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="legal">
      <a className="back" href="/">
        ← Back to Breatheasy
      </a>
      <h1>{title}</h1>
      <p className="muted">Last updated {UPDATED}</p>
      {children}
    </main>
  );
}

export function PrivacyPage() {
  const { name: OPERATOR, contact: CONTACT } = useOperator();
  return (
    <Shell title="Privacy policy">
      <p>
        Breatheasy is operated by {OPERATOR}. It suggests routes in Delhi-NCR with lower estimated air-pollution
        exposure. This page explains what we collect, why, and how to delete it. Contact: {CONTACT}.
      </p>

      <h2>Without an account</h2>
      <p>
        You can plan routes without signing in. The start and destination you enter, your travel mode and departure
        time are sent to our server to compute routes, and from there to our map and air-quality providers (below).
        We do not store these requests. Our server logs record the time, the web address path and the response status
        of each request for up to 30 days for security and troubleshooting; they do not include the places you search.
        If you use "Your location", your device shares its position with the app only for that search. Your recent
        searches are kept only in your browser on this device, never on our servers.
      </p>

      <h2>With an account (Google sign-in)</h2>
      <ul>
        <li>
          <strong>Account details from Google:</strong> your name, email address, profile picture link and Google
          account ID. We never see your Google password.
        </li>
        <li>
          <strong>Saved places</strong> you choose to save (a label such as "Home", the place name and coordinates).
        </li>
        <li>
          <strong>Trip log:</strong> when you press "Navigate" on a route while signed in, we save that trip's start
          and end (names and coordinates), departure time, travel mode, duration, distance and its estimated PM2.5
          exposure compared with the fastest route.
        </li>
      </ul>
      <p>We use this only to show you your saved places, trip history and exposure summary.</p>

      <h2>What we don't do</h2>
      <p>
        No advertising, no selling or sharing of personal data, no third-party analytics or tracking cookies. We use one
        essential cookie to keep you signed in.
      </p>

      <h2>Service providers</h2>
      <ul>
        <li>Google Cloud (hosting and database).</li>
        <li>
          Google Maps Platform (maps, place search, routes, air quality). Its use is governed by the Google Privacy
          Policy: https://policies.google.com/privacy.
        </li>
        <li>Google Identity Services (sign-in).</li>
        <li>
          When Google data is unavailable, route requests may be sent instead to OpenStreetMap-based services
          (FOSSGIS routing, Photon search, CARTO map tiles) and Open-Meteo for air quality. These requests contain the
          coordinates needed for the route, not your account details.
        </li>
      </ul>

      <h2>Retention and deletion</h2>
      <ul>
        <li>Trips are deleted automatically 12 months after you log them.</li>
        <li>Account details and saved places are kept until you delete them or your account.</li>
        <li>
          In <em>Account</em> you can download all your data, delete individual trips or places, clear your trip log,
          sign out of all devices, or delete your account. Account deletion removes everything immediately from our
          database; backups expire within 7 days.
        </li>
      </ul>

      <h2>Your rights</h2>
      <p>
        You can access, correct, export and erase your data, and withdraw consent by deleting your account. For any
        request or grievance, write to {CONTACT}; we respond within 30 days.
      </p>

      <h2>Age</h2>
      <p>Breatheasy accounts are for people aged 18 and over.</p>

      <h2>Health information</h2>
      <p>
        Exposure figures are estimates from modelled air-quality data, intended for comparing routes. They are not a
        measurement of what you breathe and not medical advice.
      </p>

      <h2>Changes</h2>
      <p>If this policy changes in a way that affects your data, we'll show a notice in the app before it applies.</p>
    </Shell>
  );
}

export function TermsPage() {
  const { name: OPERATOR, contact: CONTACT } = useOperator();
  return (
    <Shell title="Terms of use">
      <p>
        Breatheasy is provided by {OPERATOR}. By using it you agree to these terms. Contact: {CONTACT}.
      </p>
      <h2>What the app does</h2>
      <p>
        It compares available routes and estimates PM2.5 exposure on each from modelled air-quality data. Estimates can
        be wrong: air-quality models are coarse, conditions change quickly, and routes can be closed or unsafe.
      </p>
      <h2>Your responsibility</h2>
      <ul>
        <li>Use your own judgement on the road and follow traffic laws and local conditions.</li>
        <li>Don't use the app while driving or riding; set your route before you start.</li>
        <li>
          Exposure estimates are not medical advice. If you have a health condition affected by air pollution, follow
          your doctor's guidance.
        </li>
      </ul>
      <h2>Acceptable use</h2>
      <p>
        Don't misuse the service: no automated scraping, no attempts to overload or break it, no use that violates the
        Google Maps Platform terms (https://cloud.google.com/maps-platform/terms).
      </p>
      <h2>No warranty</h2>
      <p>
        The service is provided "as is", without guarantees of accuracy or availability. To the extent the law allows,
        we are not liable for losses arising from its use.
      </p>
      <h2>Governing law</h2>
      <p>These terms are governed by the laws of India.</p>
    </Shell>
  );
}
