package kr.co.disasteralert;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.AsyncTask;
import android.os.Bundle;
import android.os.IBinder;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public class RiskMonitorService extends Service implements LocationListener {
    private static final String TAG = "RiskMonitor";
    private static final int FOREGROUND_ID = 2607;
    private static final int ENTRY_ALERT_ID = 2608;
    private static final double ENTER_RADIUS_M = 500.0;
    private static final double EXIT_RADIUS_M = 750.0;
    private static final long LOCATION_INTERVAL_MS = 30_000L;
    private static final float LOCATION_DISTANCE_M = 30.0f;
    private static final long DATA_REFRESH_MS = 15 * 60 * 1000L;

    private LocationManager locationManager;
    private volatile JSONArray riskPoints;
    private volatile long riskPointsFetchedAt;
    private volatile boolean fetching;

    public static void start(Context context) {
        Intent intent = new Intent(context, RiskMonitorService.class);
        context.startForegroundService(intent);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        startForeground(FOREGROUND_ID, monitoringNotification("위험지역 진입 감시 중"));
        locationManager = getSystemService(LocationManager.class);
        refreshRiskPoints();
        registerLocationUpdates();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        registerLocationUpdates();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (locationManager != null) {
            try {
                locationManager.removeUpdates(this);
            } catch (SecurityException ignored) {
            }
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void registerLocationUpdates() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                != PackageManager.PERMISSION_GRANTED) {
            stopSelf();
            return;
        }
        for (String provider : locationManager.getProviders(true)) {
            try {
                locationManager.requestLocationUpdates(
                        provider,
                        LOCATION_INTERVAL_MS,
                        LOCATION_DISTANCE_M,
                        this
                );
            } catch (IllegalArgumentException | SecurityException ignored) {
            }
        }
    }

    @Override
    public void onLocationChanged(Location location) {
        if (System.currentTimeMillis() - riskPointsFetchedAt >= DATA_REFRESH_MS) {
            refreshRiskPoints();
        }
        evaluateEntry(location);
    }

    @Override
    public void onProviderEnabled(String provider) {
    }

    @Override
    public void onProviderDisabled(String provider) {
    }

    @Override
    public void onStatusChanged(String provider, int status, Bundle extras) {
    }

    private void refreshRiskPoints() {
        if (fetching) {
            return;
        }
        fetching = true;
        AsyncTask.execute(() -> {
            try {
                JSONObject payload = fetchJson(ServerConfig.riskPointsUrl(this));
                JSONArray points = payload.optJSONArray("points");
                if (points != null && points.length() > 0) {
                    riskPoints = points;
                    riskPointsFetchedAt = System.currentTimeMillis();
                    getSharedPreferences(ServerConfig.PREFS, MODE_PRIVATE)
                            .edit()
                            .putLong("risk_monitor_data_ms", riskPointsFetchedAt)
                            .apply();
                }
            } catch (Exception error) {
                Log.e(TAG, "Risk point refresh failed", error);
            } finally {
                fetching = false;
            }
        });
    }

    private void evaluateEntry(Location location) {
        JSONArray points = riskPoints;
        if (points == null) {
            return;
        }
        RiskPoint nearest = nearest(points, location);
        if (nearest == null) {
            return;
        }

        SharedPreferences prefs = getSharedPreferences(ServerConfig.PREFS, MODE_PRIVATE);
        boolean wasInside = prefs.getBoolean("risk_monitor_inside", false);
        boolean isInside = wasInside
                ? nearest.distanceM <= EXIT_RADIUS_M
                : nearest.distanceM <= ENTER_RADIUS_M;

        prefs.edit()
                .putBoolean("risk_monitor_inside", isInside)
                .putFloat("risk_monitor_nearest_m", (float) nearest.distanceM)
                .putString("risk_monitor_nearest_type", nearest.type)
                .putLong("risk_monitor_location_ms", System.currentTimeMillis())
                .apply();

        if (!wasInside && isInside) {
            showEntryAlert(nearest);
        }
    }

    private RiskPoint nearest(JSONArray points, Location location) {
        RiskPoint nearest = null;
        for (int index = 0; index < points.length(); index++) {
            JSONObject point = points.optJSONObject(index);
            if (point == null) {
                continue;
            }
            float[] result = new float[1];
            Location.distanceBetween(
                    location.getLatitude(),
                    location.getLongitude(),
                    point.optDouble("latitude"),
                    point.optDouble("longitude"),
                    result
            );
            if (nearest == null || result[0] < nearest.distanceM) {
                nearest = new RiskPoint(
                        point.optString("risk_type", "위험지역"),
                        point.optString("level", "확인 필요"),
                        point.optDouble("score", 0),
                        result[0]
                );
            }
        }
        return nearest;
    }

    private void showEntryAlert(RiskPoint point) {
        String title = "위험지역 진입 경보";
        String message = Math.round(point.distanceM) + "m 근처에 "
                + point.type + " 후보가 있습니다. 등급 " + point.level
                + ", 점수 " + Math.round(point.score) + "점입니다.";
        Notification notification = notificationBuilder("disaster_alerts")
                .setContentTitle(title)
                .setContentText(message)
                .setStyle(new Notification.BigTextStyle().bigText(message))
                .setCategory(Notification.CATEGORY_ALARM)
                .setPriority(Notification.PRIORITY_MAX)
                .setDefaults(Notification.DEFAULT_ALL)
                .setAutoCancel(true)
                .build();
        getSystemService(NotificationManager.class).notify(ENTRY_ALERT_ID, notification);
    }

    private Notification monitoringNotification(String text) {
        return notificationBuilder("location_monitor")
                .setContentTitle("재해 경보 위치 감시")
                .setContentText(text)
                .setCategory(Notification.CATEGORY_SERVICE)
                .setOngoing(true)
                .build();
    }

    private Notification.Builder notificationBuilder(String channel) {
        Intent intent = new Intent(this, MainActivity.class);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                this,
                0,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        return new Notification.Builder(this, channel)
                .setSmallIcon(kr.co.disasteralert.R.drawable.ic_launcher)
                .setContentIntent(pendingIntent);
    }

    private JSONObject fetchJson(String source) throws Exception {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(
                    source + "?t=" + System.currentTimeMillis()
            ).openConnection();
            connection.setConnectTimeout(10_000);
            connection.setReadTimeout(10_000);
            connection.setUseCaches(false);
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8)
            )) {
                StringBuilder body = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    body.append(line);
                }
                return new JSONObject(body.toString());
            }
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private static class RiskPoint {
        final String type;
        final String level;
        final double score;
        final double distanceM;

        RiskPoint(String type, String level, double score, double distanceM) {
            this.type = type;
            this.level = level;
            this.score = score;
            this.distanceM = distanceM;
        }
    }
}
