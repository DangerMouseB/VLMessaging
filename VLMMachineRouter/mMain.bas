Attribute VB_Name = "mMain"
'*************************************************************************************************************************************************************************************************************************************************
'
' Copyright (c) David Briant 2009-2012 - All rights reserved
'
'*************************************************************************************************************************************************************************************************************************************************

Option Explicit

Private Const STANDARD_RIGHTS_REQUIRED = &HF0000
Private Const SYNCHRONIZE = &H100000
Private Const MUTANT_QUERY_STATE = 1
Private Const MUTEX_ALL_ACCESS = STANDARD_RIGHTS_REQUIRED + SYNCHRONIZE + MUTANT_QUERY_STATE

Private Declare Function apiOpenMutex Lib "kernel32" Alias "OpenMutexA" (ByVal dwDesiredAccess As Long, ByVal bInheritHandle As Long, ByVal lpName As String) As Long
Private Declare Function apiCreateMutex Lib "kernel32" Alias "CreateMutexA" (lpMutexAttributes As Long, ByVal bInitialOwner As Long, ByVal lpName As String) As Long
Private Declare Function apiCloseHandle Lib "kernel32" Alias "CloseHandle" (ByVal hObject As Long) As Long

Private myMachineRouter As cMachineRouter
Private myHMutex As Long
Private myIsRunningInIDE As Boolean

Public Const GLOBAL_PROJECT_NAME As String = "VLMMachineRouter"

Sub Main()
    Dim lastError As Long
    ' Debug.Assert code not run in an EXE so setRunningInIDE is not called
    Debug.Assert setRunningInIDE() = True
    If myIsRunningInIDE Then
        ' should attempt to find other running instances here but for now we'll assume the developer knows what they are doing
'        If App.PrevInstance Then Exit Sub
'        myHMutex = apiOpenMutex(MUTEX_ALL_ACCESS, 0, "VLMMachineRouter")
'        If myHMutex <> 0 Then
'             Call apiCloseHandle(myHMutex)
'            Exit Sub
'        End If
    Else
        ' there are problems with App.PrevInstance so attempt to open a mutex - if it exists then we are already running so exit
        myHMutex = apiOpenMutex(MUTEX_ALL_ACCESS, 0, "VLMMachineRouterMutex")
        If myHMutex <> 0 Then Exit Sub
        myHMutex = apiCreateMutex(ByVal 0&, True, "VLMMachineRouterMutex")
        If myHMutex = 0 Then
            lastError = apiGetLastError()
            MsgBox lastError
            Exit Sub
        End If
    End If
    Set myMachineRouter = New cMachineRouter
    If False Then
        ' wierd!!! - we need the MsgBox statement in order for "If myHMutex = 0" to not always exit (or rather the apiCreateMutex to work)
        MsgBox ""
        ' (maybe the msgbox code causes a different initialisation to happen?)
    End If
End Sub
    
Sub globalShutdown()
    myMachineRouter.shutdown
    Set myMachineRouter = Nothing
    Call apiCloseHandle(myHMutex)
End Sub


Private Function setRunningInIDE() As Boolean
   myIsRunningInIDE = True
   setRunningInIDE = True
End Function

