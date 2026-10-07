#pragma once
#include <windows.h>
#include <stdint.h>

#define STUB_EXPORT __declspec(dllexport)

extern uint8_t g_zero[65536];
void stub_log(const char *fmt, ...);
void stub_seen(volatile LONG *flag, const char *name);
