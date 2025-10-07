VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
  Persistable = 0  'NotPersistable
  DataBindingBehavior = 0  'vbNone
  DataSourceBehavior  = 0  'vbNone
  MTSTransactionMode  = 0  'NotAnMTSObject
END
Attribute VB_Name = "VLMAddress"
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

Private myMachineID As Long
Private myRouterID As Integer
Private myAgentID As Integer


'*************************************************************************************************************************************************************************************************************************************************
' Initialize / Release
'*************************************************************************************************************************************************************************************************************************************************

Sub initialise(MachineID As Long, RouterID As Integer, AgentID As Integer)
    myMachineID = MachineID
    myRouterID = RouterID
    myAgentID = AgentID
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' MessageArray conversion
'*************************************************************************************************************************************************************************************************************************************************

Sub fromMessageArray(messageArray As Variant)
    myMachineID = messageArray(1)
    myRouterID = messageArray(2)
    myAgentID = messageArray(3)
End Sub

Function asMessageArray() As Variant
    Dim answer As Variant
    DBCreateNewVariantArray answer, 1, 3
    answer(1) = myMachineID
    answer(2) = myRouterID
    answer(3) = myAgentID
    asMessageArray = answer
End Function


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
Property Get AgentID() As Integer
    AgentID = myAgentID
End Property

Property Let AgentID(AgentID As Integer)
    myAgentID = AgentID
End Property



