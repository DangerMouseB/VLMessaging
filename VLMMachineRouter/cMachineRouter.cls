VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
  Persistable = 0  'NotPersistable
  DataBindingBehavior = 0  'vbNone
  DataSourceBehavior  = 0  'vbNone
  MTSTransactionMode  = 0  'NotAnMTSObject
END
Attribute VB_Name = "cMachineRouter"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = True
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = False
'*************************************************************************************************************************************************************************************************************************************************
'
' Copyright (c) David Briant 2009-2012 - All rights reserved
'
'*************************************************************************************************************************************************************************************************************************************************

Option Explicit

' error reporting
Private Const MODULE_NAME As String = "cMachineRouter"
Private Const MODULE_VERSION As String = "0.0.0.1"

Private WithEvents myMouseEventsForm As fMouseEventsForm
Attribute myMouseEventsForm.VB_VarHelpID = -1
Private WithEvents myAST As cTP_AdvSysTray
Attribute myAST.VB_VarHelpID = -1

Private myClassName As String
Private myWindowName As String
Private Const TEN_MILLION As Single = 10000000

Private WithEvents myListener As VLMessaging.VLMMMFileListener
Attribute myListener.VB_VarHelpID = -1
Private WithEvents myMMFileTransports As VLMessaging.VLMMMFileTransports
Attribute myMMFileTransports.VB_VarHelpID = -1

Private myMachineID As Long

Private myRouterSeed As Long
Private myRouterIDsByMMTransportID As New Dictionary
Private myMMTransportIDsByRouterID As New Dictionary

Private myDirectoryEntriesByIDString As New Dictionary

Private myVLMUtils As New VLMUtils


Private Const GET_ROUTER_ID As String = "GET_ROUTER_ID"
Private Const GET_ROUTER_ID_REPLY As String = "GET_ROUTER_ID_REPLY"
Private Const REGISTER_SERVICE As String = "REGISTER_SERVICE"
Private Const REGISTER_SERVICE_REPLY As String = "REGISTER_SERVICE_REPLY"
Private Const UNREGISTER_SERVICE As String = "UNREGISTER_SERVICE"
Private Const UNREGISTER_SERVICE_REPLY As String = "UNREGISTER_SERVICE_REPLY"
Private Const GET_SERVICES As String = "GET_SERVICES"
Private Const GET_SERVICES_REPLY As String = "GET_SERVICES_REPLY"
Private Const PING As String = "PING"
Private Const PING_REPLY As String = "PING_REPLY"
Private Const SERVICE_DEREGISTERED As String = "SERVICE_DEREGISTERED"


'*************************************************************************************************************************************************************************************************************************************************
' Initialize / Release
'*************************************************************************************************************************************************************************************************************************************************

Private Sub class_Initialize()
    Dim atomID As Long
    ' hide us from the Applications list in the Windows Task Manager
    App.TaskVisible = False
    
    ' listen for connections
    Randomize
    myClassName = "VLMMachineRouter" & CStr(Int(Rnd() * TEN_MILLION) + 1)
    Randomize
    myWindowName = "VLMMachineRouter" & CStr(Int(Rnd() * TEN_MILLION) + 1)
    Set myListener = New VLMMMFileListener
    myListener.listenViaNamedWindow myClassName, myWindowName, 1024# * 64#         ' 64K buffer size - we should add streaming at some point
    Set myMMFileTransports = New VLMMMFileTransports
    myRouterSeed = 1
    
    ' create tray icon
    Set myMouseEventsForm = New fMouseEventsForm
    Set myAST = New cTP_AdvSysTray
    myAST.create myMouseEventsForm, myMouseEventsForm.icon, "VLM Directory"
    'myAST.showBalloon "Current Shell32.dll version is " & myAST.shellVersion & ".x", "AdvSysTray VB Class", NIIF_INFO
    
    ' make myself easily found
    apiSetPropA myMouseEventsForm.hWnd, "IsVLMMachineRouter", 1
    apiSetPropA myMouseEventsForm.hWnd, "WindowNameAtom", apiGlobalAddAtomA(myWindowName)
    apiSetPropA myMouseEventsForm.hWnd, "ClassNameAtom", apiGlobalAddAtomA(myClassName)
    
End Sub

Sub shutdown()
    myAST.destroy
    Set myAST = Nothing
    Unload myMouseEventsForm
    Set myMouseEventsForm = Nothing
End Sub

Private Sub myAST_RButtonUp()
    Dim epm As New cTP_EasyPopupMenu, menuItemSelected As Long
    'SetForegroundWindow myMouseEventsForm.hwnd
'    epm.addMenuItem "Main form...", MF_STRING, 1
'    epm.createSubmenu "Radio items"
'    epm.addSubmenuItem "Radio item 1", MF_STRING, 2
'    epm.addSubmenuItem "Radio item 2", MF_STRING, 3
'    epm.addSubmenuItem "Radio item 3", MF_STRING, 4
'    epm.checkRadioItem 0, 2, 1
'    epm.addMenuItem "", MF_SEPARATOR, 0
'    epm.addMenuItem "Disabled item", MF_GRAYED, 5
'    epm.addMenuItem "Checked item", MF_CHECKED, 6
'    epm.addMenuItem "", MF_SEPARATOR, 0
    epm.addMenuItem "Exit", MF_STRING, 12
    apiSetForegroundWindow myMouseEventsForm.hWnd
    menuItemSelected = epm.trackMenu(myMouseEventsForm.hWnd)
    Select Case menuItemSelected
        Case 12
            Set epm = Nothing
            globalShutdown
    End Select
End Sub

Private Sub myListener_newTransport(ByVal newTransport As VLMessaging.VLMMMFileTransport, oReceived As Boolean)
    Dim id As Long
    oReceived = True
    id = myMMFileTransports.addTransport(newTransport)
End Sub

Private Function messageFromBytes(buffer() As Byte) As VLMMessage
    Dim i1 As Long, i2 As Long, messageArray() As Variant, message As New VLMMessage
    DBGetArrayBounds buffer, 1, i1, i2
    messageArray = myVLMUtils.BytesAsVariant(buffer, i2 + 1, 1)
    message.fromMessageArray messageArray
    Set messageFromBytes = message
End Function

Private Function messageToBytes(message As VLMMessage) As Byte()
    Dim messageArray() As Variant, length As Long, buffer() As Byte
    messageArray = message.asMessageArray
    length = myVLMUtils.LengthOfVariantAsBytes(messageArray)
    DBCreateNewArrayOfBytes buffer, 1, length
    myVLMUtils.VariantAsBytes messageArray, buffer, length + 1, 1
    messageToBytes = buffer
End Function

Private Sub myMMFileTransports_bytesArrived(ByVal id As Long, buffer() As Byte, oReceived As Boolean)
    Dim message As VLMMessage, toAddress As VLMAddress
1    oReceived = True
2    Set message = messageFromBytes(buffer)
3    Set toAddress = message.toAddress
4    On Error GoTo errorHandler
5    If (toAddress.MachineID = myMachineID Or toAddress.MachineID = 0) And toAddress.RouterID = 1 And toAddress.AgentID = 1 Then
6        handleMessageToRouter id, message
7    Else
8        routeMessage message
9    End If
Exit Sub
errorHandler:
    VBTrace Err.Description & ", " & Erl
End Sub

Sub handleMessageToRouter(MMFileTransportID As Long, message As VLMMessage)
    Dim reply As VLMMessage, transport As VLMMMFileTransport, RouterID As Long, address As New VLMAddress, serviceType As String
    Dim IDString As String, vs As Variant, i As Long, entries As New Collection, answer1D As Variant
    
    VBTrace message.subject
    
    Select Case True
    
        Case message.subject = GET_ROUTER_ID
            If myRouterIDsByMMTransportID.Exists(MMFileTransportID) Then
                RouterID = myRouterIDsByMMTransportID(MMFileTransportID)
            Else
                myRouterSeed = myRouterSeed + 1
                RouterID = myRouterSeed
                myRouterIDsByMMTransportID(MMFileTransportID) = RouterID
                myMMTransportIDsByRouterID(RouterID) = MMFileTransportID
            End If
            Set reply = message.reply
            reply.subject = GET_ROUTER_ID_REPLY
            reply.Contents = RouterID
            Set transport = myMMFileTransports.transport(MMFileTransportID)
            transport.send messageToBytes(reply)
            VBTrace reply.subject
            
        Case message.subject = REGISTER_SERVICE
            address.fromMessageArray message.Contents(2)
            myDirectoryEntriesByIDString(directoryEntryIDString(CStr(message.Contents(1)), address)) = message.Contents
            Set reply = message.reply
            reply.subject = REGISTER_SERVICE_REPLY
            Set transport = myMMFileTransports.transport(MMFileTransportID)
            transport.send messageToBytes(reply)
            VBTrace reply.subject
        
        Case message.subject = UNREGISTER_SERVICE
            address.fromMessageArray message.Contents(2)
            IDString = directoryEntryIDString(CStr(message.Contents(1)), address)
            If myDirectoryEntriesByIDString.Exists(IDString) Then myDirectoryEntriesByIDString.Remove IDString
            Set reply = message.reply
            reply.subject = UNREGISTER_SERVICE_REPLY
            Set transport = myMMFileTransports.transport(MMFileTransportID)
            transport.send messageToBytes(reply)
            VBTrace reply.subject
        
        Case message.subject = PING_REPLY
            ' if I don't know them then they have been deregistered so send them a SERVICE_DEREGISTERED
            ' if they are in the pingedAt list then move them to the heardAtList

        Case message.subject = GET_SERVICES
            vs = myDirectoryEntriesByIDString.Items
            If IsEmpty(message.Contents) Then
                For i = 0 To UBound(vs)
                    entries.Add vs(i)
                Next
            Else
                serviceType = message.Contents
                For i = 0 To UBound(vs)
                    If vs(i)(1) = serviceType Then entries.Add vs(i)
                Next
            End If
            If entries.Count > 0 Then
                ReDim answer1D(1 To entries.Count)
                For i = 1 To entries.Count
                    answer1D(i) = entries(i)
                Next
            End If
            Set reply = message.reply
            reply.subject = GET_SERVICES_REPLY
            reply.Contents = answer1D
            Set transport = myMMFileTransports.transport(MMFileTransportID)
            transport.send messageToBytes(reply)
            VBTrace reply.subject
            
    End Select

End Sub

Sub routeMessage(message As VLMMessage)
    Dim buffer() As Byte, transport As VLMMMFileTransport
    If message.toAddress.MachineID <> 0 And message.toAddress.MachineID <> myMachineID Then
        ' route to a remote machine
    Else
        ' for the moment just route between MMFileTransports
        If myMMTransportIDsByRouterID.Exists(message.toAddress.RouterID) Then
            Set transport = myMMFileTransports(myMMTransportIDsByRouterID(message.toAddress.RouterID))
            transport.send messageToBytes(message)
        End If
    End If
End Sub

Function directoryEntryIDString(serviceType As String, address As VLMAddress)
    directoryEntryIDString = serviceType & "<" & address.MachineID & "," & address.RouterID & "," & address.AgentID & ">"
End Function

Private Sub myMMFileTransports_connected(ByVal id As Long, oReceived As Boolean)
    oReceived = True
End Sub

Private Sub myMMFileTransports_disconnecting(ByVal id As Long, oReceived As Boolean)
    oReceived = True
End Sub

Private Sub myMouseEventsForm_PingTimer()
    ' are there any services that haven't heard from in a while? if so send them PING messages
    ' are there any services that have timed out on their PING_REPLYs?
    ' if so deregister them and send them a SERVICE_DEREGISTERED (if they are still alive they can reregister themselves)
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' module summary
'*************************************************************************************************************************************************************************************************************************************************

Private Function ModuleSummary() As Variant()
    ModuleSummary = Array(1, GLOBAL_PROJECT_NAME, MODULE_NAME, MODULE_VERSION)
End Function

