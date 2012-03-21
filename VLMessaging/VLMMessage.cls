VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
  Persistable = 0  'NotPersistable
  DataBindingBehavior = 0  'vbNone
  DataSourceBehavior  = 0  'vbNone
  MTSTransactionMode  = 0  'NotAnMTSObject
END
Attribute VB_Name = "VLMMessage"
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

Private mySchemaID As Byte
Private myFromAddress As New VLMAddress
Private myToAddress As New VLMAddress
Private myMessageID As Long
Private myRequestID As Long
Private mySubject As String
Private myContents As Variant
Private myReserved As Variant


'*************************************************************************************************************************************************************************************************************************************************
' Initialize / Release
'*************************************************************************************************************************************************************************************************************************************************

Private Sub Class_Initialize()
    mySchemaID = 1
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' MessageArray conversion
'*************************************************************************************************************************************************************************************************************************************************

Sub fromMessageArray(messageArray As Variant)
    mySchemaID = messageArray(1)
    myFromAddress.initialise CLng(messageArray(2)), CInt(messageArray(3)), CInt(messageArray(4))
    myToAddress.initialise CLng(messageArray(5)), CInt(messageArray(6)), CInt(messageArray(7))
    myMessageID = messageArray(8)
    myRequestID = messageArray(9)
    mySubject = messageArray(10)
    myContents = messageArray(11)
    myReserved = messageArray(12)
End Sub

Function asMessageArray() As Variant
    Dim answer As Variant
    DBCreateNewVariantArray answer, 1, 12
    answer(1) = mySchemaID
    answer(2) = myFromAddress.MachineID
    answer(3) = myFromAddress.RouterID
    answer(4) = myFromAddress.AgentID
    answer(5) = myToAddress.MachineID
    answer(6) = myToAddress.RouterID
    answer(7) = myToAddress.AgentID
    answer(8) = myMessageID
    answer(9) = myRequestID
    answer(10) = mySubject
    answer(11) = myContents
    answer(12) = myReserved
    asMessageArray = answer
End Function


'*************************************************************************************************************************************************************************************************************************************************
' Reply
'*************************************************************************************************************************************************************************************************************************************************

Function reply() As VLMMessage
    Set reply = New VLMMessage
    reply.fromAddress.initialise Me.toAddress.MachineID, Me.toAddress.RouterID, Me.toAddress.AgentID
    reply.toAddress.initialise Me.fromAddress.MachineID, Me.fromAddress.RouterID, Me.fromAddress.AgentID
    reply.requestID = Me.messageID
End Function


'*************************************************************************************************************************************************************************************************************************************************
' Accessing
'*************************************************************************************************************************************************************************************************************************************************

Property Get schemaID() As Byte
    schemaID = mySchemaID
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get fromAddress() As VLMAddress
    Set fromAddress = myFromAddress
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get toAddress() As VLMAddress
    Set toAddress = myToAddress
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get messageID() As Long
    messageID = myMessageID
End Property

Property Let messageID(anID As Long)
    myMessageID = anID
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get requestID() As Long
    requestID = myRequestID
End Property

Property Let requestID(anID As Long)
    myRequestID = anID
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get subject() As String
    subject = mySubject
End Property

Property Let subject(aSubject As String)
    mySubject = aSubject
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get contents() As Variant
    contents = myContents
End Property

Property Let contents(aContents As Variant)
    myContents = aContents
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get reserved() As Variant
    reserved = myReserved
End Property

Property Let reserved(anArray As Variant)
    myReserved = anArray
End Property


