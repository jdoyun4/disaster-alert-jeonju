package kr.co.disasteralert;

import android.content.Context;
import android.content.SharedPreferences;

public final class ServerConfig {
    public static final String PREFS = "disaster_alert_settings";
    public static final String KEY_BASE_URL = "base_url";
    private static final String DEFAULT_BASE_URL =
            "https://jdoyun4.github.io/disaster-alert-jeonju";

    private ServerConfig() {}

    public static String baseUrl(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String value = prefs.getString(KEY_BASE_URL, DEFAULT_BASE_URL);
        if (value == null || value.trim().isEmpty()) {
            value = DEFAULT_BASE_URL;
        }
        value = value.trim();
        if (value.contains(":8765") || value.startsWith("http://10.")) {
            value = DEFAULT_BASE_URL;
            prefs.edit().putString(KEY_BASE_URL, value).apply();
        }
        while (value.endsWith("/")) {
            value = value.substring(0, value.length() - 1);
        }
        return value;
    }

    public static String dashboardUrl(Context context) {
        return baseUrl(context) + "/";
    }

    public static String alertStatusUrl(Context context) {
        return baseUrl(context) + "/rainfall_alert_status.json";
    }

    public static String riskPointsUrl(Context context) {
        return baseUrl(context) + "/risk_points.json";
    }
}
