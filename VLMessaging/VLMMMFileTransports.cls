VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
  Persistable = 0  'NotPersistable
  DataBindingBehavior = 0  'vbNone
  DataSourceBehavior  = 0  'vbNone
  MTSTransactionMode  = 0  'NotAnMTSObject
END
Attribute VB_Name = "VLMMMFileTransports"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = True
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = True
'*************************************************************************************************************************************************************************************************************************************************
'
' Copyright (c) David Briant 2009-2011 - All rights reserved
'
'*************************************************************************************************************************************************************************************************************************************************

Option Explicit

' error reporting
Private Const MODULE_NAME As String = "VLMMMFileTransports"
Private Const MODULE_VERSION As String = "0.0.0.1"


Event connected(ByVal id As Long, oReceived As Boolean)
Event disconnected(ByVal id As Long)
Event disconnecting(ByVal id As Long, oReceived As Boolean)
Event bytesArrived(ByVal id As Long, buffer() As Byte, oReceived As Boolean)

Private myTransports As New Dictionary
Private myIDSeed As Long

Function addTransport(aTransport As VLMMMFileTransport) As Long
1     myIDSeed = myIDSeed + 1
2     myTransports.Add myIDSeed, aTransport
3     Set aTransport.callback = Me
4     aTransport.friend_id = myIDSeed
5     addTransport = myIDSeed
End Function

Sub removeTransport(anID As Long)
1     Dim aTransport As VLMMMFileTransport, errorState() As Variant
2     Const METHOD_NAME As String = "removeConnection"
3     On Error GoTo exceptionHandler
4    If myTransports.exists(anID) Then
5         DBTrace ModuleSummary(), METHOD_NAME, "myTransports.exists(anID) anID: " & anID
6        Set aTransport = myTransports(anID)
'30        aTransport.friend_id = 0            ' this changes anID because all the vars were by ref!!!! interesting
7        Set aTransport.callback = Nothing
8             On Error Resume Next
9        myTransports.remove anID
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

Function transport(anID As Long) As VLMMMFileTransport
1     If myTransports.exists(anID) Then Set transport = myTransports(anID)
End Function

Function count() As Long
1     count = myTransports.count
End Function

Function transportIDs() As Long()
1     transportIDs = DBSubArray(myTransports.keys, , , , , , , vbLong, 1)
End Function

Private Sub Class_Terminate()
1     Dim items1D As Variant, i As Long, i1 As Long, i2 As Long, transport As VLMMMFileTransport
2     items1D = myTransports.Items
3     DBGetArrayBounds items1D, 1, i1, i2
4     For i = i1 To i2
5         Set transport = items1D(i)
6         Set transport.callback = Nothing
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

Friend Sub bytesArrived(id As Long, buffer() As Byte, received As Boolean)
1     RaiseEvent bytesArrived(id, buffer, received)
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' module summary
'*************************************************************************************************************************************************************************************************************************************************

Private Function ModuleSummary() As Variant()
    ModuleSummary = Array(1, GLOBAL_PROJECT_NAME, MODULE_NAME, MODULE_VERSION)
End Function

