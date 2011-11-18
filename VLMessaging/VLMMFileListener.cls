VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
  Persistable = 0  'NotPersistable
  DataBindingBehavior = 0  'vbNone
  DataSourceBehavior  = 0  'vbNone
  MTSTransactionMode  = 0  'NotAnMTSObject
END
Attribute VB_Name = "VLMMFileListener"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = True
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = True
'*************************************************************************************************************************************************************************************************************************************************
'            COPYRIGHT NOTICE
'
' Copyright (C) David Briant 2009 - All rights reserved
'
'*************************************************************************************************************************************************************************************************************************************************

Option Explicit

' error reporting
Private Const MODULE_NAME As String = "VLMMFileListener"
Private Const MODULE_VERSION As String = "0.0.0.1"

Private Const NEW_CONNECTION_TIMER_ID As Long = 1
Private Const TIMER_INTERVAL As Long = 2000

Event newConnection(ByVal newConnection As VLMMFileTransport, oReceived As Boolean)

Private myClassName As String
Private myWindowName As String
Private myListeningHwnd As Long            ' a publically visable window so others can make connection requests to me
Private myMMFileSize As Long

' some state to help ensure Excel gets the events
Private myNewConnectionQueue As New Collection


'*************************************************************************************************************************************************************************************************************************************************
' Publicising
'*************************************************************************************************************************************************************************************************************************************************

Sub publiciseViaNamedWindow(className As String, windowName As String, MMFileSize As Long)
    myClassName = className
    myWindowName = windowName
    myMMFileSize = MMFileSize
    
    ensureClassExists className
    
    ' create a new window so others can make connection requests to me
    myListeningHwnd = apiCreateWindowExA( _
        WS_EX_TRANSPARENT, _
        className, _
        windowName, _
        WS_OVERLAPPED, 0&, 0&, 0&, 0&, _
        HWND_MESSAGE, 0&, _
        CLng(App.hInstance), 0&)
    
    addMMFileListener myListeningHwnd, Me
    
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' Debug Accessing
'*************************************************************************************************************************************************************************************************************************************************

Property Get listeningHwnd() As Long
    listeningHwnd = myListeningHwnd
End Property


'*************************************************************************************************************************************************************************************************************************************************
' Accessing
'*************************************************************************************************************************************************************************************************************************************************

Property Get className() As String
    className = myClassName
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get windowName() As String
    windowName = myWindowName
End Property


'*************************************************************************************************************************************************************************************************************************************************
' WndProc processing
'*************************************************************************************************************************************************************************************************************************************************

Friend Sub processWinProc(ByVal lMsg As Long, ByVal wparam As Long, ByVal lparam As Long)
    Dim remoteHwnd As Long, received As Boolean, newConnection As VLMMFileTransport, firstConnection As VLMMFileTransport
    Const METHOD_NAME As String = "processWinProc"
    
    On Error GoTo exceptionHandler
    
    Select Case lMsg
        Case g_connectionRequestMessageID
            remoteHwnd = wparam
            If remoteHwnd = 0 Then Exit Sub  ' problem in protocol
            Set newConnection = New VLMMFileTransport
            newConnection.initializeUsingRemoteHwnd remoteHwnd, myClassName, myMMFileSize
            myNewConnectionQueue.Add newConnection
            Do
                Set firstConnection = myNewConnectionQueue(1)
                received = False
                RaiseEvent newConnection(firstConnection, received)   ' excel can block if it does queue the messages and kick off a timer
                If received Then myNewConnectionQueue.remove 1
            Loop While myNewConnectionQueue.count > 0 And received
            If myNewConnectionQueue.count > 0 Then
                Call apiSetTimer(myListeningHwnd, NEW_CONNECTION_TIMER_ID, TIMER_INTERVAL, API_NULL)         ' the timer will fire every 50mS in an attempt to deliver the events
                If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myListeningHwnd & ": newConnection() not received starting NEW_CONNECTION_TIMER"
            End If

        Case WM_TIMER
            If wparam = NEW_CONNECTION_TIMER_ID Then
                If myNewConnectionQueue.count > 0 Then
                    Do
                        Set firstConnection = myNewConnectionQueue(1)
                        received = False
                        RaiseEvent newConnection(firstConnection, received)
                        If received Then myNewConnectionQueue.remove 1
                    Loop While myNewConnectionQueue.count > 0 And received
                    If received Then
                        Call apiKillTimer(myListeningHwnd, NEW_CONNECTION_TIMER_ID)
                        If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myListeningHwnd & ": killing NEW_CONNECTION_TIMER"
                    End If
                Else
                    Call apiKillTimer(myListeningHwnd, NEW_CONNECTION_TIMER_ID)
                    If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myListeningHwnd & ": killing NEW_CONNECTION_TIMER"
                End If
            End If
                
    End Select
Exit Sub
exceptionHandler:
    DBTraceError ModuleSummary(), METHOD_NAME, DBErrors_errorState()
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' Initialize / Release
'*************************************************************************************************************************************************************************************************************************************************

Private Sub Class_Initialize()
    ensureWindowsMessagesExist
End Sub

Private Sub Class_Terminate()
    If myListeningHwnd <> 0 Then
        DBTrace ModuleSummary(), "Class_Terminate", "destroying window"
        removeMMFileListener myListeningHwnd
        apiDestroyWindow myListeningHwnd
    End If
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' module summary
'*************************************************************************************************************************************************************************************************************************************************

Private Function ModuleSummary() As Variant()
    ModuleSummary = Array(1, GLOBAL_PROJECT_NAME, MODULE_NAME, MODULE_VERSION)
End Function

