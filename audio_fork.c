/*
 * audio_fork.c - C version of audio_fork.js
 * Freeswitch audio streaming application using ESL
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <esl.h>
#include <json-c/json.h>

// 事件定义
#define EVENT_TRANSCRIPT "mod_audio_fork::transcription"
#define EVENT_TRANSFER "mod_audio_fork::transfer"
#define EVENT_PLAY_AUDIO "mod_audio_fork::play_audio"
#define EVENT_KILL_AUDIO "mod_audio_fork::kill_audio"
#define EVENT_DISCONNECT "mod_audio_fork::disconnect"
#define EVENT_CONNECT "mod_audio_fork::connect"
#define EVENT_CONNECT_FAILED "mod_audio_fork::connect_failed"
#define EVENT_MAINTENANCE "mod_audio_fork::maintenance"
#define EVENT_ERROR "mod_audio_fork::error"

typedef struct {
    esl_handle_t *handle;
    char *uuid;
    char *ws_url;
} session_data_t;

// 事件处理函数
void on_connect(esl_event_t *event) {
    printf("successfully connected\n");
}

void on_connect_failed(esl_event_t *event) {
    printf("connection failed\n");
}

void on_disconnect(esl_event_t *event) {
    printf("far end dropped connection\n");
}

void on_error(esl_event_t *event) {
    printf("got error: %s\n", event->body ? event->body : "unknown error");
}

void on_maintenance(esl_event_t *event) {
    printf("got event: %s\n", event->body ? event->body : "unknown event");
}

// 处理DTMF事件
void handle_dtmf(esl_event_t *event, session_data_t *session) {
    const char *dtmf = esl_event_get_header(event, "DTMF-Digit");
    if (dtmf) {
        char cmd[1024];
        snprintf(cmd, sizeof(cmd), "uuid_audio_fork %s send_text %s", session->uuid, dtmf);
        esl_send_recv(session->handle, cmd);
    }
}

// 初始化音频流转发
int init_audio_fork(session_data_t *session, const char *call_id, 
                   const char *to_uri, const char *from_uri) {
    char cmd[2048];
    char metadata[1024];
    
    // 构建metadata JSON
    snprintf(metadata, sizeof(metadata), 
             "{\"callId\":\"%s\",\"to\":\"%s\",\"from\":\"%s\"}",
             call_id, to_uri, from_uri);
    
    // 播放静音
    esl_send_recv(session->handle, "playback silence_stream://1000");
    
    // 使用Google TTS播放欢迎消息
    snprintf(cmd, sizeof(cmd), 
             "speak google_tts:en-GB-Wavenet-A 'Hi there. Please go ahead and make a recording and then hangup'");
    esl_send_recv(session->handle, cmd);
    
    // 启动音频流转发
    snprintf(cmd, sizeof(cmd), 
             "uuid_audio_fork %s start %s mono 16000 %s",
             session->uuid, session->ws_url, metadata);
    
    if (esl_send_recv(session->handle, cmd) != ESL_SUCCESS) {
        printf("Failed to start audio fork: %s\n", session->handle->last_reply);
        return -1;
    }
    
    return 0;
}

// 处理新通道事件
void handle_channel_answer(esl_event_t *event, session_data_t *session) {
    const char *call_id = esl_event_get_header(event, "variable_sip_call_id");
    const char *to_uri = esl_event_get_header(event, "variable_sip_to_uri");
    const char *from_uri = esl_event_get_header(event, "variable_sip_from_uri");
    
    printf("Channel answered: %s\n", session->uuid);
    
    // 初始化音频流转发
    if (init_audio_fork(session, call_id, to_uri, from_uri) < 0) {
        printf("Failed to initialize audio fork\n");
    }
}

// 事件处理主循环
void event_handler(esl_event_t *event, session_data_t *session) {
    const char *event_name = esl_event_get_header(event, "Event-Name");
    const char *event_subclass = esl_event_get_header(event, "Event-Subclass");
    
    if (event_name && strcmp(event_name, "CUSTOM") == 0) {
        if (event_subclass) {
            if (strcmp(event_subclass, EVENT_CONNECT) == 0) {
                on_connect(event);
            } else if (strcmp(event_subclass, EVENT_CONNECT_FAILED) == 0) {
                on_connect_failed(event);
            } else if (strcmp(event_subclass, EVENT_DISCONNECT) == 0) {
                on_disconnect(event);
            } else if (strcmp(event_subclass, EVENT_ERROR) == 0) {
                on_error(event);
            } else if (strcmp(event_subclass, EVENT_MAINTENANCE) == 0) {
                on_maintenance(event);
            }
        }
    } else if (event_name && strcmp(event_name, "DTMF") == 0) {
        handle_dtmf(event, session);
    } else if (event_name && strcmp(event_name, "CHANNEL_ANSWER") == 0) {
        handle_channel_answer(event, session);
    }
}

int main(int argc, char *argv[]) {
    esl_handle_t handle = {{0}};
    session_data_t session = {0};
    esl_status_t status;
    
    if (argc < 2) {
        printf("Usage: %s <websocket_url> [freeswitch_host] [freeswitch_port] [freeswitch_password]\n", argv[0]);
        printf("Example: %s ws://localhost:8080 localhost 8021 ClueCon\n", argv[0]);
        return 1;
    }
    
    session.ws_url = argv[1];
    const char *host = argc > 2 ? argv[2] : "localhost";
    int port = argc > 3 ? atoi(argv[3]) : 8021;
    const char *password = argc > 4 ? argv[4] : "ClueCon";
    
    printf("Connecting to FreeSWITCH at %s:%d\n", host, port);
    printf("Audio will be streamed to: %s\n", session.ws_url);
    
    // 连接到FreeSWITCH ESL
    status = esl_connect(&handle, host, port, NULL, password);
    if (status != ESL_SUCCESS) {
        printf("Failed to connect to FreeSWITCH: %s\n", handle.last_reply);
        return 1;
    }
    
    printf("Connected to FreeSWITCH\n");
    
    // 订阅事件
    esl_events(&handle, ESL_EVENT_TYPE_CUSTOM, 
               EVENT_CONNECT " " EVENT_CONNECT_FAILED " " EVENT_DISCONNECT " " 
               EVENT_ERROR " " EVENT_MAINTENANCE);
    esl_events(&handle, ESL_EVENT_TYPE_CHANNEL, "DTMF CHANNEL_ANSWER");
    
    // 主事件循环
    while ((status = esl_recv_event(&handle, 1, NULL)) == ESL_SUCCESS) {
        if (handle.last_event) {
            event_handler(handle.last_event, &session);
            esl_event_destroy(&handle.last_event);
        }
    }
    
    printf("Disconnected from FreeSWITCH\n");
    esl_disconnect(&handle);
    
    return 0;
}