VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
  Persistable = 0  'NotPersistable
  DataBindingBehavior = 0  'vbNone
  DataSourceBehavior  = 0  'vbNone
  MTSTransactionMode  = 0  'NotAnMTSObject
END
Attribute VB_Name = "VLMessage"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = True
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = True
'*************************************************************************************************************************************************************************************************************************************************
'            COPYRIGHT NOTICE
'
' Copyright (C) David Briant 2011 - All rights reserved
'
'*************************************************************************************************************************************************************************************************************************************************

Option Explicit

Private mySchemaID As Byte
Private myFromAddress As New VLAddress
Private myToAddress As New VLAddress
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
' Serialisation
'*************************************************************************************************************************************************************************************************************************************************

Sub fromBytes(buffer1D() As Byte)
    Dim i1 As Long, i2 As Long, messageArray As Variant
    DBGetArrayBounds buffer1D, 1, i1, i2
    messageArray = DBBytesAsVariant(buffer1D, i2 + 1, 1)
    mySchemaID = messageArray(1)
    myFromAddress.initialise CLng(messageArray(2)), CInt(messageArray(3)), CInt(messageArray(4))
    myToAddress.initialise CLng(messageArray(5)), CInt(messageArray(6)), CInt(messageArray(7))
    myMessageID = messageArray(8)
    myRequestID = messageArray(9)
    mySubject = messageArray(10)
    myContents = messageArray(11)
    myReserved = messageArray(12)
End Sub

Sub toBytes(oBuffer1D() As Byte)
    Dim messageArray As Variant, length As Long
    DBCreateNewVariantArray messageArray, 1, 12
    messageArray(1) = mySchemaID
    messageArray(2) = myFromAddress.MachineID
    messageArray(3) = myFromAddress.RouterID
    messageArray(4) = myFromAddress.ConnectionID
    messageArray(5) = myToAddress.MachineID
    messageArray(6) = myToAddress.RouterID
    messageArray(7) = myToAddress.ConnectionID
    messageArray(8) = myMessageID
    messageArray(9) = myRequestID
    messageArray(10) = mySubject
    messageArray(11) = myContents
    messageArray(12) = myReserved
    length = DBLengthOfVariantAsBytes(messageArray)
    DBCreateNewArrayOfBytes oBuffer1D, 1, length
    DBVariantAsBytes messageArray, oBuffer1D, length + 1, 1
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' Reply
'*************************************************************************************************************************************************************************************************************************************************

Function reply() As VLMessage
    Set reply = New VLMessage
    reply.fromAddress.initialise Me.toAddress.MachineID, Me.toAddress.RouterID, Me.toAddress.ConnectionID
    reply.toAddress.initialise Me.fromAddress.MachineID, Me.fromAddress.RouterID, Me.fromAddress.ConnectionID
    reply.requestID = Me.messageID
End Function


'*************************************************************************************************************************************************************************************************************************************************
' Accessing
'*************************************************************************************************************************************************************************************************************************************************

Property Get schemaID() As Byte
    schemaID = mySchemaID
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get fromAddress() As VLAddress
    Set fromAddress = myFromAddress
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get toAddress() As VLAddress
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


