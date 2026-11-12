#include <windows.h>
#include <wchar.h>
#include <stdio.h>

int WINAPI wWinMain(HINSTANCE instance,HINSTANCE previous,PWSTR command,int show) {
    wchar_t directory[32768], python[32768], script[32768], arguments[65536];
    DWORD length=GetModuleFileNameW(NULL,directory,32768);
    if (!length || length>=32768) return 1;
    wchar_t *slash=wcsrchr(directory,L'\\');
    if (!slash) return 1;
    *slash=L'\0';
    if (swprintf(python,32768,L"%ls\\runtime\\pythonw.exe",directory)<0 ||
        swprintf(script,32768,L"%ls\\app\\desktop_launcher.py",directory)<0 ||
        swprintf(arguments,65536,L"\"%ls\" \"%ls\"",python,script)<0) return 1;
    STARTUPINFOW startup={0};
    PROCESS_INFORMATION process={0};
    startup.cb=sizeof(startup);
    if (!CreateProcessW(python,arguments,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,directory,&startup,&process)) {
        MessageBoxW(NULL,L"Library Workbench could not open its bundled Python runtime.\nExtract the complete ZIP to a folder, then run Library Workbench.exe.",L"Library Workbench",MB_OK|MB_ICONERROR);
        return 1;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
