package kr.co.disasteralert;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.media.AudioAttributes;
import android.media.RingtoneManager;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.webkit.GeolocationPermissions;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

public class MainActivity extends Activity {
    private static final int PERMISSION_REQUEST = 100;
    private static final int BACKGROUND_LOCATION_REQUEST = 101;
    private WebView webView;
    private TextView syncStatus;
    private boolean loadingRemote;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        createNotificationChannel();
        requestAppPermissions();
        SyncJobService.schedule(this);
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED) {
            RiskMonitorService.start(this);
        }
        buildScreen();
        loadLatest();
    }

    private void buildScreen() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(248, 250, 252));
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(
                    0,
                    insets.getSystemWindowInsetTop(),
                    0,
                    insets.getSystemWindowInsetBottom()
            );
            return insets;
        });

        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setOrientation(LinearLayout.HORIZONTAL);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(18, 12, 12, 12);
        toolbar.setBackgroundColor(Color.rgb(17, 24, 39));

        syncStatus = new TextView(this);
        syncStatus.setTextColor(Color.WHITE);
        syncStatus.setTextSize(14);
        syncStatus.setText("최신 자료 연결 중");
        toolbar.addView(syncStatus, new LinearLayout.LayoutParams(0, -2, 1));

        Button refresh = new Button(this);
        refresh.setText("새로고침");
        refresh.setOnClickListener(v -> loadLatest());
        toolbar.addView(refresh);

        Button settings = new Button(this);
        settings.setText("주소");
        settings.setOnClickListener(v -> showServerDialog());
        toolbar.addView(settings);

        root.addView(toolbar, new LinearLayout.LayoutParams(-1, -2));

        webView = new WebView(this);
        root.addView(webView, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);

        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.getSettings().setDatabaseEnabled(true);
        webView.getSettings().setGeolocationEnabled(true);
        webView.getSettings().setAllowFileAccess(true);
        webView.getSettings().setAllowContentAccess(true);
        webView.getSettings().setMixedContentMode(0);
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onGeolocationPermissionsShowPrompt(
                    String origin,
                    GeolocationPermissions.Callback callback
            ) {
                boolean granted = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                        == PackageManager.PERMISSION_GRANTED;
                callback.invoke(origin, granted, false);
            }
        });
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                if (loadingRemote && url.startsWith("http")) {
                    view.evaluateJavascript(
                            "(function(){return document.body && document.body.innerText ? document.body.innerText.length : 0;})()",
                            result -> {
                                int textLength = 0;
                                try {
                                    textLength = Integer.parseInt(result.replace("\"", ""));
                                } catch (Exception ignored) {
                                }
                                if (textLength > 20) {
                                    loadingRemote = false;
                                    syncStatus.setText("최신 자료 연결됨");
                                } else {
                                    showOffline("온라인 자료 연결 안 됨 · 저장된 지도 표시");
                                }
                            }
                    );
                }
            }

            @Override
            public void onReceivedError(
                    WebView view,
                    WebResourceRequest request,
                    WebResourceError error
            ) {
                if (request.isForMainFrame() && loadingRemote) {
                    showOffline("온라인 자료 연결 안 됨 · 저장된 지도 표시");
                }
            }
        });
    }

    private void showOffline(String message) {
        if (!loadingRemote) {
            return;
        }
        loadingRemote = false;
        syncStatus.setText(message);
        webView.loadUrl("file:///android_asset/index.html");
    }

    private void loadLatest() {
        loadingRemote = true;
        syncStatus.setText("최신 자료 확인 중");
        webView.loadUrl(ServerConfig.dashboardUrl(this) + "?t=" + System.currentTimeMillis());
    }

    private void showServerDialog() {
        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setText(ServerConfig.baseUrl(this));
        input.setSelectAllOnFocus(true);
        input.setPadding(32, 16, 32, 16);

        new AlertDialog.Builder(this)
                .setTitle("온라인 분석 주소")
                .setMessage("기본 주소는 자동 갱신되는 온라인 재해 지도입니다.")
                .setView(input)
                .setPositiveButton("저장", (dialog, which) -> {
                    String value = input.getText().toString().trim();
                    if (!value.isEmpty()) {
                        SharedPreferences prefs = getSharedPreferences(
                                ServerConfig.PREFS,
                                Context.MODE_PRIVATE
                        );
                        prefs.edit().putString(ServerConfig.KEY_BASE_URL, value).apply();
                        SyncJobService.schedule(this);
                        loadLatest();
                    }
                })
                .setNegativeButton("취소", null)
                .setNeutralButton("경보 시험", (dialog, which) ->
                        RiskMonitorService.notifyTest(this)
                )
                .show();
    }

    private void requestAppPermissions() {
        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissions(
                    new String[]{
                            Manifest.permission.ACCESS_FINE_LOCATION,
                            Manifest.permission.ACCESS_COARSE_LOCATION,
                            Manifest.permission.POST_NOTIFICATIONS
                    },
                    PERMISSION_REQUEST
            );
        } else {
            requestPermissions(
                    new String[]{
                            Manifest.permission.ACCESS_FINE_LOCATION,
                            Manifest.permission.ACCESS_COARSE_LOCATION
                    },
                    PERMISSION_REQUEST
            );
        }
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode,
            String[] permissions,
            int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == PERMISSION_REQUEST
                && checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED) {
            RiskMonitorService.start(this);
            if (Build.VERSION.SDK_INT >= 29
                    && checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
                    != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(
                        new String[]{Manifest.permission.ACCESS_BACKGROUND_LOCATION},
                        BACKGROUND_LOCATION_REQUEST
                );
            }
        } else if (requestCode == BACKGROUND_LOCATION_REQUEST
                && checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED) {
            RiskMonitorService.start(this);
        }
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(
                    "disaster_alerts",
                    "재해 위험 경고",
                    NotificationManager.IMPORTANCE_HIGH
            );
            channel.setDescription("강우량과 위치 기반 위험 경고");
            getSystemService(NotificationManager.class).createNotificationChannel(channel);

            NotificationChannel entryChannel = new NotificationChannel(
                    "risk_entry_alerts",
                    "위험지역 진입 경보",
                    NotificationManager.IMPORTANCE_HIGH
            );
            entryChannel.setDescription("위험지역 진입 시 소리와 진동으로 경고합니다.");
            entryChannel.enableVibration(true);
            entryChannel.setVibrationPattern(new long[]{0, 700, 250, 700, 250, 1000});
            entryChannel.setSound(
                    RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM),
                    new AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_ALARM)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                            .build()
            );
            getSystemService(NotificationManager.class).createNotificationChannel(entryChannel);

            NotificationChannel monitorChannel = new NotificationChannel(
                    "location_monitor",
                    "위험지역 위치 감시",
                    NotificationManager.IMPORTANCE_LOW
            );
            monitorChannel.setDescription("백그라운드에서 위험지역 진입을 확인합니다.");
            getSystemService(NotificationManager.class).createNotificationChannel(monitorChannel);
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
