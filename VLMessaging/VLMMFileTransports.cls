VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
  Persistable = 0  'NotPersistable
  DataBindingBehavior = 0  'vbNone
  DataSourceBehavior  = 0  'vbNone
  MTSTransactionMode  = 0  'NotAnMTSObject
END
Attribute VB_Name = "VLMMFileTransports"
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
Private Const MODULE_NAME As String = "VLMMFileTransports"
Private Const MODULE_VERSION As String = "0.0.0.1"


Event connected(ByVal id As Long, oReceived As Boolean)
Event disconnected(ByVal id As Long)
Event disconnecting(ByVal id As Long, oReceived As Boolean)
Event messageArrived(ByVal id As Long, buffer() As Byte, oReceived As Boolean)

Private myConnections As New Dictionary
Private myIDSeed As Long

Function addConnection(aConnection As VLMMFileTransport) As Long
1     myIDSeed = myIDSeed + 1
2     myConnections.Add myIDSeed, aConnection
3     Set aConnection.callback = Me
4     aConnection.friend_id = myIDSeed
5     addConnection = myIDSeed
End Function

Sub removeConnection(anID As Long)
1     Dim aConnection As VLMMFileTransport, errorState() As Variant
2     Const METHOD_NAME As String = "removeConnection"
3     On Error GoTo exceptionHandler
4    If myConnections.exists(anID) Then
5         DBTrace ModuleSummary(), METHOD_NAME, "myConnections.exists(anID) anID: " & anID
6        Set aConnection = myConnections(anID)
'30        aConnection.friend_id = 0            ' this changes anID because all the vars were by ref!!!! interesting
7        Set aConnection.callback = Nothing
8             On Error Resume Next
9        myConnections.remove anID
10         errorState = DBErrors_errorState()
11         If DBErrors_errorStateNumber(errorState) <> 0 Then
12             DBTraceError ModuleSummary(), METHOD_NAME, errorState
13             DBTrace ModuleSummary(), METHOD_NAME, "Figure out and correct one day!!! - anID: " & anID
14         End If
15    End If
16 Exit Sub
17 exceptionHandler:
18     errorState = DBErrors_errorState()
19     DBTraceError ModuleSummary(), METHOD_NAME, errorState
20     DBTrace ModuleSummary(), METHOD_NAME, "Erl: " & Erl & " anID: " & anID
21     DBErrors_reraiseErrorStateFrom errorState, ModuleSummary(), METHOD_NAME
End Sub

Function connection(anID As Long) As VLMMFileTransport
1     If myConnections.exists(anID) Then Set connection = myConnections(anID)
End Function

Function count() As Long
1     count = myConnections.count
End Function

Function connectionIDs() As Long()
1     connectionIDs = DBSubArray(myConnections.keys, , , , , , , vbLong, 1)
End Function

Private Sub Class_Terminate()
1     Dim items1D As Variant, i As Long, i1 As Long, i2 As Long, connection As VLMMFileTransport
2     items1D = myConnections.Items
3     DBGetArrayBounds items1D, 1, i1, i2
4     For i = i1 To i2
5         Set connection = items1D(i)
6         Set connection.callback = Nothing
7     Next
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' callback to event propagation
'*************************************************************************************************************************************************************************************************************************************************

Friend Sub connected(id As Long, received As Boolean)
1     RaiseEvent connected(id, received)
End Sub

Friend Sub disconnected(id As Long)
1     RaiseEvent disconnected(id)
End Sub

Friend Sub disconnecting(id As Long, received As Boolean)
1     RaiseEvent disconnecting(id, received)
End Sub

Friend Sub messageArrived(id As Long, buffer() As Byte, received As Boolean)
1     RaiseEvent messageArrived(id, buffer, received)
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' module summary
'*************************************************************************************************************************************************************************************************************************************************

Private Function ModuleSummary() As Variant()
    ModuleSummary = Array(1, GLOBAL_PROJECT_NAME, MODULE_NAME, MODULE_VERSION)
End Function

