Attribute VB_Name = "mGlobals"
'*************************************************************************************************************************************************************************************************************************************************
'            COPYRIGHT NOTICE
'
' Copyright (C) David Briant 2009 - All rights reserved
'
'*************************************************************************************************************************************************************************************************************************************************

' TODO
' expose asMessageArray and fromMessageArray on VLMessage
' make VLAddress a public type - no behaviour






Option Explicit

' error reporting
Private Const MODULE_NAME As String = "Globals"
Private Const MODULE_VERSION As String = "0.0.0.1"

Public Const GLOBAL_PROJECT_NAME As String = "VLMessaging"
Public Const SHOW_TRACE As Boolean = False

Public Const VL_MESSAGING_CONNECTION_REQUEST As String = "VLConnectionRequest"
Public Const VL_MESSAGING_CONNECTION_AGREED As String = "VLConnectionAgreed"
Public Const VL_MESSAGING_AGREEMENT_ACKNOWLEDGED As String = "VLAgreementAcknowledged"
Public Const VL_MESSAGING_DISCONNECT As String = "VLDisconnect"

Public Const VL_MESSAGING_MESSAGE_IN_TRANSIT As String = "VLMessageInTransit"
Public Const VL_MESSAGING_MESSAGE_RECEIVED As String = "VLMessageReceived"
Public Const VL_MESSAGING_MESSAGE_GARBLED As String = "VLMessageGarbled"

Public g_connectionRequestMessageID As Long
Public g_connectionAgreedMessageID As Long
Public g_agreementAcknowledgedMessageID As Long
Public g_connectionDisconnectMessageID As Long

Public g_messageInTransitID As Long
Public g_messageReceivedMessageID As Long
Public g_messageGarbledMessageID As Long

Private myWindowsClasses As New Dictionary
Private myMMFileTransports As New VLWeakDictionary
Private myMMFileListeners As New VLWeakDictionary
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

Sub addMMFileTransport(hwnd As Long, MMFileTransport As VLMMFileTransport)
    Const METHOD_NAME = "addMMFileTransport"
    If myMMFileTransports.exists(CStr(hwnd)) Then DBErrors_raiseGeneralError ModuleSummary, METHOD_NAME, "hwnd already registered"
    Set myMMFileTransports(CStr(hwnd)) = MMFileTransport
End Sub

Sub removeMMFileTransport(hwnd As Long)
    Const METHOD_NAME = "removeMMFileTransport"
    If myMMFileTransports.exists(CStr(hwnd)) Then myMMFileTransports.remove CStr(hwnd)
End Sub

Sub addMMFileListener(hwnd As Long, MMFileListener As VLMMFileListener)
    Const METHOD_NAME = "addMMFileListener"
    If myMMFileListeners.exists(CStr(hwnd)) Then DBErrors_raiseGeneralError ModuleSummary, METHOD_NAME, "hwnd already registered"
    Set myMMFileListeners(CStr(hwnd)) = MMFileListener
End Sub

Sub removeMMFileListener(hwnd As Long)
    myMMFileListeners.remove CStr(hwnd)
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' Window Procedure
'*************************************************************************************************************************************************************************************************************************************************

Function VLMessaging_WndProc(ByVal hwnd As Long, ByVal lMsg As Long, ByVal wparam As Long, ByVal lparam As Long) As Long
    Dim MMFileListener As VLMMFileListener, MMFileTransport As VLMMFileTransport

    VLMessaging_WndProc = 0  ' Success
    
    Select Case lMsg
    
        Case WM_TIMER
            If myMMFileListeners.exists(CStr(hwnd)) Then
                Set MMFileListener = myMMFileListeners(CStr(hwnd))
                MMFileListener.processWinProc lMsg, wparam, lparam
            End If
            If myMMFileTransports.exists(CStr(hwnd)) Then
                Set MMFileTransport = myMMFileTransports(CStr(hwnd))
                MMFileTransport.processWinProc lMsg, wparam, lparam
            End If

        Case g_connectionRequestMessageID
            If myMMFileListeners.exists(CStr(hwnd)) Then
                Set MMFileListener = myMMFileListeners(CStr(hwnd))
                MMFileListener.processWinProc lMsg, wparam, lparam
            End If
        
        Case g_connectionAgreedMessageID, g_agreementAcknowledgedMessageID, g_connectionDisconnectMessageID, g_messageInTransitID, g_messageReceivedMessageID, g_messageGarbledMessageID
            If myMMFileTransports.exists(CStr(hwnd)) Then
                Set MMFileTransport = myMMFileTransports(CStr(hwnd))
                MMFileTransport.processWinProc lMsg, wparam, lparam
            End If
            
        Case Else
            VLMessaging_WndProc = apiDefWindowProcA(hwnd, lMsg, wparam, lparam)            ' Return whatever the default window procedure returns.
            
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
