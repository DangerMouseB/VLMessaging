Attribute VB_Name = "mGlobals"
'*************************************************************************************************************************************************************************************************************************************************
'
' Copyright (c) David Briant 2009-2011 - All rights reserved
'
'*************************************************************************************************************************************************************************************************************************************************

Option Explicit

' error reporting
Private Const MODULE_NAME As String = "mGlobals"
Private Const MODULE_VERSION As String = "0.0.0.1"

Public Const GLOBAL_PROJECT_NAME As String = "VLMessaging"
Public Const SHOW_TRACE As Boolean = False

Public Const VL_MESSAGING_CONNECTION_REQUEST As String = "VLMConnectionRequest"
Public Const VL_MESSAGING_CONNECTION_AGREED As String = "VLMConnectionAgreed"
Public Const VL_MESSAGING_AGREEMENT_ACKNOWLEDGED As String = "VLMAgreementAcknowledged"
Public Const VL_MESSAGING_DISCONNECT As String = "VLMDisconnect"

Public Const VL_MESSAGING_MESSAGE_IN_TRANSIT As String = "VLMMessageInTransit"
Public Const VL_MESSAGING_MESSAGE_RECEIVED As String = "VLMMessageReceived"
Public Const VL_MESSAGING_MESSAGE_GARBLED As String = "VLMMessageGarbled"

Public g_connectionRequestMessageID As Long
Public g_connectionAgreedMessageID As Long
Public g_agreementAcknowledgedMessageID As Long
Public g_connectionDisconnectMessageID As Long

Public g_messageInTransitID As Long
Public g_messageReceivedMessageID As Long
Public g_messageGarbledMessageID As Long

Private myWindowsClasses As New Dictionary
Private myMMFileTransports As New VLMWeakDictionary
Private myMMFileListeners As New VLMWeakDictionary
Private myWindowsMessagesHaveBeenCreated As Boolean


'*************************************************************************************************************************************************************************************************************************************************
' Windows Classes management
'*************************************************************************************************************************************************************************************************************************************************

Sub Main()
    InitVBoost
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' Windows Classes management
'*************************************************************************************************************************************************************************************************************************************************

Sub ensureClassExists(className As String)
    Dim wcx As WNDCLASSEX, classAtomID As Long, errorState() As Variant
    Const METHOD_NAME As String = "ensureClassExists"
    On Error GoTo exceptionHandler
    If Not myWindowsClasses.exists(className) Then
        wcx.cbSize = Len(wcx)
        wcx.style = CS_GLOBALCLASS
        wcx.lpfnwndproc = DBFunctionPointer(AddressOf VLMessaging_WndProc)
        wcx.hInstance = App.hInstance
        wcx.lpszClassName = className
        classAtomID = apiRegisterClassExA(wcx)
        If classAtomID = 0 Then MsgBox "classAtomID = 0"
        myWindowsClasses(className) = classAtomID
    End If
Exit Sub
exceptionHandler:
    errorState = DBErrors_errorState()
    DBTraceError ModuleSummary(), METHOD_NAME, errorState
    DBErrors_reraiseErrorStateFrom errorState, ModuleSummary(), METHOD_NAME
End Sub

Sub cleanUpClasses()
    Dim keys As Variant, i As Long
    keys = myWindowsClasses.keys
    For i = 0 To myWindowsClasses.count - 1
        apiUnregisterClassA CStr(keys(i)), App.hInstance
    Next
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' Windows Messges management
'*************************************************************************************************************************************************************************************************************************************************

Sub ensureWindowsMessagesExist()
    If Not myWindowsMessagesHaveBeenCreated Then
        g_connectionRequestMessageID = apiRegisterWindowMessageA(VL_MESSAGING_CONNECTION_REQUEST)
        g_connectionAgreedMessageID = apiRegisterWindowMessageA(VL_MESSAGING_CONNECTION_AGREED)
        g_agreementAcknowledgedMessageID = apiRegisterWindowMessageA(VL_MESSAGING_AGREEMENT_ACKNOWLEDGED)
        g_connectionDisconnectMessageID = apiRegisterWindowMessageA(VL_MESSAGING_DISCONNECT)
        
        g_messageInTransitID = apiRegisterWindowMessageA(VL_MESSAGING_MESSAGE_IN_TRANSIT)
        g_messageReceivedMessageID = apiRegisterWindowMessageA(VL_MESSAGING_MESSAGE_RECEIVED)
        g_messageGarbledMessageID = apiRegisterWindowMessageA(VL_MESSAGING_MESSAGE_GARBLED)
        myWindowsMessagesHaveBeenCreated = True
    End If
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' Transport / Listener management
'*************************************************************************************************************************************************************************************************************************************************

Sub addMMFileTransport(hWnd As Long, MMFileTransport As VLMMMFileTransport)
    Const METHOD_NAME = "addMMFileTransport"
    If myMMFileTransports.exists(CStr(hWnd)) Then DBErrors_raiseGeneralError ModuleSummary, METHOD_NAME, "hwnd already registered"
    Set myMMFileTransports(CStr(hWnd)) = MMFileTransport
End Sub

Sub removeMMFileTransport(hWnd As Long)
    Const METHOD_NAME = "removeMMFileTransport"
    If myMMFileTransports.exists(CStr(hWnd)) Then myMMFileTransports.remove CStr(hWnd)
End Sub

Sub addMMFileListener(hWnd As Long, MMFileListener As VLMMMFileListener)
    Const METHOD_NAME = "addMMFileListener"
    If myMMFileListeners.exists(CStr(hWnd)) Then DBErrors_raiseGeneralError ModuleSummary, METHOD_NAME, "hwnd already registered"
    Set myMMFileListeners(CStr(hWnd)) = MMFileListener
End Sub

Sub removeMMFileListener(hWnd As Long)
    myMMFileListeners.remove CStr(hWnd)
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' Window Procedure
'*************************************************************************************************************************************************************************************************************************************************

Function VLMessaging_WndProc(ByVal hWnd As Long, ByVal lMsg As Long, ByVal wparam As Long, ByVal lparam As Long) As Long
    Dim MMFileListener As VLMMMFileListener, MMFileTransport As VLMMMFileTransport

    VLMessaging_WndProc = 0  ' Success
    
    Select Case lMsg
    
        Case WM_TIMER
            If myMMFileListeners.exists(CStr(hWnd)) Then
                Set MMFileListener = myMMFileListeners(CStr(hWnd))
                MMFileListener.processWinProc lMsg, wparam, lparam
            End If
            If myMMFileTransports.exists(CStr(hWnd)) Then
                Set MMFileTransport = myMMFileTransports(CStr(hWnd))
                MMFileTransport.processWinProc lMsg, wparam, lparam
            End If

        Case g_connectionRequestMessageID
            If myMMFileListeners.exists(CStr(hWnd)) Then
                Set MMFileListener = myMMFileListeners(CStr(hWnd))
                MMFileListener.processWinProc lMsg, wparam, lparam
            End If
        
        Case g_connectionAgreedMessageID, g_agreementAcknowledgedMessageID, g_connectionDisconnectMessageID, g_messageInTransitID, g_messageReceivedMessageID, g_messageGarbledMessageID
            If myMMFileTransports.exists(CStr(hWnd)) Then
                Set MMFileTransport = myMMFileTransports(CStr(hWnd))
                MMFileTransport.processWinProc lMsg, wparam, lparam
            End If
            
        Case Else
            VLMessaging_WndProc = apiDefWindowProcA(hWnd, lMsg, wparam, lparam)            ' Return whatever the default window procedure returns.
            
    End Select
    
End Function


'*************************************************************************************************************************************************************************************************************************************************
' Utilities
'*************************************************************************************************************************************************************************************************************************************************

Function MMFileName(hwndSender As Long, hwndReceiver As Long) As String
    MMFileName = hwndSender & ":" & hwndReceiver
End Function


'*************************************************************************************************************************************************************************************************************************************************
' module summary
'*************************************************************************************************************************************************************************************************************************************************

Private Function ModuleSummary() As Variant()
    ModuleSummary = Array(1, GLOBAL_PROJECT_NAME, MODULE_NAME, MODULE_VERSION)
End Function
