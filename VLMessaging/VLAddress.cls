VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
  Persistable = 0  'NotPersistable
  DataBindingBehavior = 0  'vbNone
  DataSourceBehavior  = 0  'vbNone
  MTSTransactionMode  = 0  'NotAnMTSObject
END
Attribute VB_Name = "VLAddress"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = True
'*************************************************************************************************************************************************************************************************************************************************
'            COPYRIGHT NOTICE
'
' Copyright (C) David Briant 2011 - All rights reserved
'
'*************************************************************************************************************************************************************************************************************************************************

Option Explicit

Private myMachineID As Long
Private myRouterID As Integer
Private myConnectionID As Integer


'*************************************************************************************************************************************************************************************************************************************************
' Initialize / Release
'*************************************************************************************************************************************************************************************************************************************************

Sub initialise(MachineID As Long, RouterID As Integer, ConnectionID As Integer)
    myMachineID = MachineID
    myRouterID = RouterID
    myConnectionID = ConnectionID
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' Accessing
'*************************************************************************************************************************************************************************************************************************************************

Property Get MachineID() As Long
    MachineID = myMachineID
End Property

Property Let MachineID(MachineID As Long)
    myMachineID = MachineID
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get RouterID() As Integer
    RouterID = myRouterID
End Property

Property Let RouterID(RouterID As Integer)
    myRouterID = RouterID
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get ConnectionID() As Integer
    ConnectionID = myConnectionID
End Property

Property Let ConnectionID(ConnectionID As Integer)
    myConnectionID = ConnectionID
End Property



