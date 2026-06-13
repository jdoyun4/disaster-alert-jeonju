package kr.co.disasteralert;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationManager;
import android.os.AsyncTask;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public class SyncJobService extends JobService {
    private static final String TAG = "DisasterAlertSync";
    private static final int JOB_ID = 260612;
    private static final int NOTIFICATION_ID = 2606;
    private static final double ALERT_RADIUS_M = 500.0;
    private static final double RAIN_RADIUS_M = 1500.0;
    private static final long REPEAT_INTERVAL_MS = 3 * 60 * 60 * 1000L;

    public static void schedule(Context context) {
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        JobInfo job = new JobInfo.Builder(
                JOB_ID,
                new ComponentName(context, SyncJobService.class)
        )
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true)
                .setPeriodic(15 * 60 * 1000L)
                .build();
        scheduler.schedule(job);
    }

    public static void notifyTest(Context context) {
        showNotification(
                context,
                "재해 경보 시험",
                "알림 소리와 표시가 정상적으로 작동합니다."
        );
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        AsyncTask.execute(() -> {
            checkAlerts();
            jobFinished(params, false);
        });
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }

    private void checkAlerts() {
        SharedPreferences prefs = getSharedPreferences(
                ServerConfig.PREFS,
                Context.MODE_PRIVATE
        );
        try {
            JSONObject alertStatus = fetchJson(ServerConfig.alertStatusUrl(this));
            JSONObject riskPayload = fetchJson(ServerConfig.riskPointsUrl(this));
            Location location = latestLocation();

            int warning = alertStatus.optInt("warning_count", 0);
            int emergency = alertStatus.optInt("emergency_count", 0);
            JSONObject counts = alertStatus.optJSONObject("alert_counts");
            if (counts != null) {
                warning = Math.max(warning, counts.optInt("주의 경고", 0));
                emergency = Math.max(emergency, counts.optInt("긴급 경고", 0));
            }

            RiskPoint nearest = nearestRiskPoint(riskPayload.optJSONArray("points"), location);
            String state = "normal";
            String title = "";
            String message = "";

            if ((warning > 0 || emergency > 0)
                    && (location == null || nearest == null || nearest.distanceM <= RAIN_RADIUS_M)) {
                state = "rain-" + warning + "-" + emergency;
                title = "강우 침수 위험 경고";
                message = "주의 " + warning + "곳, 긴급 " + emergency
                        + "곳이 예보 기준을 넘었습니다.";
                if (nearest != null) {
                    message += " 가장 가까운 " + nearest.type + " 후보까지 "
                            + Math.round(nearest.distanceM) + "m입니다.";
                }
            } else if (nearest != null && nearest.distanceM <= ALERT_RADIUS_M) {
                state = "near-" + nearest.type + "-" + Math.round(nearest.distanceM / 100.0);
                title = "현재 위치 주변 위험 후보";
                message = Math.round(nearest.distanceM) + "m 근처에 "
                        + nearest.type + " 후보가 있습니다. 위험 점수 "
                        + Math.round(nearest.score) + "점입니다.";
            }

            prefs.edit()
                    .putLong("last_sync_ms", System.currentTimeMillis())
                    .putString("last_sync_result", "ok")
                    .putString("last_alert_state", state)
                    .apply();

            if (!"normal".equals(state) && shouldNotify(prefs, state)) {
                showNotification(this, title, message);
                prefs.edit()
                        .putString("last_notified_state", state)
                        .putLong("last_notified_ms", System.currentTimeMillis())
                        .apply();
            }
            Log.i(TAG, "sync=ok warning=" + warning + " emergency=" + emergency
                    + " nearest_m=" + (nearest == null ? "none" : Math.round(nearest.distanceM)));
        } catch (Exception error) {
            prefs.edit()
                    .putLong("last_sync_ms", System.currentTimeMillis())
                    .putString("last_sync_result", error.getClass().getSimpleName())
                    .apply();
            Log.e(TAG, "Alert sync failed", error);
        }
    }

    private boolean shouldNotify(SharedPreferences prefs, String state) {
        String previous = prefs.getString("last_notified_state", "");
        long previousTime = prefs.getLong("last_notified_ms", 0L);
        return !state.equals(previous)
                || System.currentTimeMillis() - previousTime >= REPEAT_INTERVAL_MS;
    }

    private JSONObject fetchJson(String source) throws Exception {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(source + "?t=" + System.currentTimeMillis());
            connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(10000);
            connection.setReadTimeout(10000);
            connection.setUseCaches(false);
            int status = connection.getResponseCode();
            if (status < 200 || status >= 300) {
                throw new IllegalStateException("HTTP " + status);
            }
            BufferedReader reader = new BufferedReader(
                    new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8)
            );
            StringBuilder body = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                body.append(line);
            }
            reader.close();
            return new JSONObject(body.toString());
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private Location latestLocation() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                != PackageManager.PERMISSION_GRANTED) {
            return null;
        }
        LocationManager manager = getSystemService(LocationManager.class);
        Location best = null;
        for (String provider : manager.getProviders(true)) {
            try {
                Location candidate = manager.getLastKnownLocation(provider);
                if (candidate != null && (best == null || candidate.getTime() > best.getTime())) {
                    best = candidate;
                }
            } catch (SecurityException ignored) {
            }
        }
        return best;
    }

    private RiskPoint nearestRiskPoint(JSONArray points, Location location) {
        if (points == null || location == null) {
            return null;
        }
        RiskPoint nearest = null;
        for (int index = 0; index < points.length(); index++) {
            JSONObject point = points.optJSONObject(index);
            if (point == null) {
                continue;
            }
            float[] distance = new float[1];
            Location.distanceBetween(
                    location.getLatitude(),
                    location.getLongitude(),
                    point.optDouble("latitude"),
                    point.optDouble("longitude"),
                    distance
            );
            if (nearest == null || distance[0] < nearest.distanceM) {
                nearest = new RiskPoint(
                        point.optString("risk_type", "위험"),
                        point.optDouble("score", 0),
                        distance[0]
                );
            }
        }
        return nearest;
    }

    private static void showNotification(Context context, String title, String text) {
        Intent intent = new Intent(context, MainActivity.class);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                context,
                0,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        Notification notification = new Notification.Builder(context, "disaster_alerts")
                .setSmallIcon(kr.co.disasteralert.R.drawable.ic_launcher)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setContentIntent(pendingIntent)
                .setAutoCancel(true)
                .build();
        context.getSystemService(NotificationManager.class)
                .notify(NOTIFICATION_ID, notification);
    }

    private static class RiskPoint {
        final String type;
        final double score;
        final double distanceM;

        RiskPoint(String type, double score, double distanceM) {
            this.type = type;
            this.score = score;
            this.distanceM = distanceM;
        }
    }
}
