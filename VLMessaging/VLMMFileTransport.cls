VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
  Persistable = 0  'NotPersistable
  DataBindingBehavior = 0  'vbNone
  DataSourceBehavior  = 0  'vbNone
  MTSTransactionMode  = 0  'NotAnMTSObject
END
Attribute VB_Name = "VLMMFileTransport"
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
Private Const MODULE_NAME As String = "VLMMFileTransport"
Private Const MODULE_VERSION As String = "0.0.0.1"

Private Const MMFILE_HEADER_SIZE As Long = 4
Private Const MESSAGE_ARRIVED_TIMER_ID As Long = 1
Private Const CONNECTED_TIMER_ID As Long = 2
Private Const DISCONNECTING_TIMER_ID As Long = 3
Private Const TIMER_INTERVAL As Long = 50

Event messageArrived(buffer() As Byte, oReceived As Boolean)
Event connected(oReceived As Boolean)
Event disconnecting(oReceived As Boolean)
Event disconnected()

Private myID As Long
Private myCallbackPtr As Long

Private myHwnd As Long
Private myRemoteHwnd As Long
Private myMMFileHandle As Long
Private myMMFileBaseAddr As Long
Private myMMFileSize As Long
Private myRemoteMMFileHandle As Long
Private myRemoteMMFileBaseAddr As Long
Private myRemoteMMFileSize As Long

' message sending handshake
Private myIsSending As Boolean
Private mySendQueue As New Collection

' connection state
Private myIsDisconnecting As Boolean
Private myIsConnecting As Boolean
Private myIsConnected As Boolean
Private myIsWaitingForConnectionAcceptance As Boolean

' some state to help ensure Excel gets the events
Private myMessageInTransitQueue As New Collection


'*************************************************************************************************************************************************************************************************************************************************
' Message Sending
'*************************************************************************************************************************************************************************************************************************************************

Function send(buffer1D() As Byte) As Long
56     Const METHOD_NAME As String = "send"

    ' check if the last message has been read if not - wait (or put in my internal queue?)
    ' if we keep an internal queue then the client needs full access since we are not going to add multithreading to keep pushing the data
    ' besides not reading a queue is pretty terminal? not so I can send messages quicker than 2 postmessages can fly accross the machine... so not just excel...
61     If Not myIsConnected And Not myIsConnecting Then DBErrors_raiseGeneralError ModuleSummary, METHOD_NAME, "Not connected"
62     mySendQueue.Add buffer1D
63     If myIsSending Or myIsConnecting Then
64         If mySendQueue.count > 1000 Then DBErrors_raiseGeneralError ModuleSummary, METHOD_NAME, "1000 messages in queue"
65         Exit Function
66     End If
    
68     privateSendMessage

70     If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, "send"

End Function

Private Sub privateSendMessage()
75     Dim i1 As Long, i2 As Long, length As Long, buffer As String, retval As Long, lastError As Long, buffer1D() As Byte
76     Const METHOD_NAME As String = "privateSendMessage"
    
78     myIsSending = True
79     buffer1D = mySendQueue(1)
80     mySendQueue.remove 1
81     DBGetArrayBounds buffer1D, 1, i1, i2, length
82     If (length + MMFILE_HEADER_SIZE) > myMMFileSize Then DBErrors_raiseGeneralError ModuleSummary, METHOD_NAME, "MMFile not big enough for message"
83     apiCopyMemory ByVal myMMFileBaseAddr, length, 4
84     apiCopyMemory ByVal myMMFileBaseAddr + 4, buffer1D(i1), length
85     retval = apiPostMessageA(myRemoteHwnd, g_messageInTransitID, myHwnd, 0)
86     If retval = 0 Then
87         lastError = apiGetLastError()
88         buffer = Space(200)
89         length = apiFormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM, ByVal API_NULL, lastError, LANG_NEUTRAL, buffer, 200, ByVal API_NULL)
90         If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": apiPostMessageA error (1): " & Left(buffer, length)
91         DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "1: " & Left(buffer, length)
92     End If
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' Accessing
'*************************************************************************************************************************************************************************************************************************************************

Property Get id() As Long
113     id = myID
End Property

Friend Property Let friend_id(anID As Long)
117     myID = anID
End Property

'*************************************************************************************************************************************************************************************************************************************************
Friend Property Set callback(anObject As VLMMFileTransports)
122     myCallbackPtr = ObjPtr(anObject)
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get isConnecting() As Boolean
113     isConnecting = myIsConnecting
End Property

'*************************************************************************************************************************************************************************************************************************************************
Property Get isConnected() As Boolean
113     isConnected = myIsConnected
End Property


'*************************************************************************************************************************************************************************************************************************************************
' Connecting / Disconnecting
'*************************************************************************************************************************************************************************************************************************************************

Friend Sub initializeUsingRemoteHwnd(remoteHwnd As Long, className As String, MMSize As Long)
131     Dim retval As Long, buffer As String, length As Long, lastError As Long, errorState() As Variant
132     Const METHOD_NAME As String = "initializeUsingRemoteHwnd"
    
134     On Error GoTo exceptionHandler
    
136     If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, "initializeUsingRemoteHwnd - enter"

138     myIsConnecting = True
139     myRemoteHwnd = remoteHwnd
140     myMMFileSize = MMSize
    
    ' create my window -     ' DB - http://msdn.microsoft.com/en-us/library/ms632680%28VS.85%29.aspx
143     ensureClassExists className
144     myHwnd = apiCreateWindowExA( _
        WS_EX_TRANSPARENT, _
        className, _
        "", _
        WS_OVERLAPPED, 0&, 0&, 0&, 0&, _
        HWND_MESSAGE, 0&, _
        CLng(App.hInstance), 0&)
151     addMMFileTransport myHwnd, Me
        
153     createMyMMFile
154     If SHOW_TRACE Then DBTrace ModuleSummary, METHOD_NAME, myHwnd & ": create(1) MMFile " & MMFileName(myHwnd, myRemoteHwnd)
    
    ' let the other end know we've agreed the connection
157     myIsWaitingForConnectionAcceptance = True
158     retval = apiPostMessageA(myRemoteHwnd, g_connectionAgreedMessageID, myHwnd, myMMFileSize)
159     If retval = 0 Then
160         lastError = apiGetLastError()
161         buffer = Space(200)
162         length = apiFormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM, ByVal API_NULL, lastError, LANG_NEUTRAL, buffer, 200, ByVal API_NULL)
163         If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": apiPostMessageA error (1): " & Left(buffer, length)
164         DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "1: " & Left(buffer, length)
165     End If
    
167     If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, "initializeUsingRemoteHwnd - exit"
    
169 Exit Sub
170 exceptionHandler:
171     errorState = DBErrors_errorState()
172     myIsConnecting = False
173     DBTraceError ModuleSummary(), METHOD_NAME, errorState
174     DBErrors_reraiseErrorStateFrom errorState, ModuleSummary(), METHOD_NAME
End Sub


Sub connectViaNamedWindow(className As String, windowName As String, MMSize As Long)
179     Dim listeningHwnd As Long, buffer As String, length As Long, retval As Long, lastError As Long, errorState() As Variant
180     Const METHOD_NAME As String = "connectViaNamedWindow"
    
182     On Error GoTo exceptionHandler
    
184     myIsConnecting = True
185    myMMFileSize = MMSize

    ' find the remote window
188    listeningHwnd = apiFindWindowExA(HWND_MESSAGE, 0, className, windowName)
189    If listeningHwnd = 0 Then DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "Can't find window """ & windowName & """ of class """ & className & """"
    
    ' create my window to receive windows messages
192    ensureClassExists className
193    myHwnd = apiCreateWindowExA( _
        WS_EX_TRANSPARENT, _
        className, _
        "Inbox", _
        WS_OVERLAPPED, 0&, 0&, 0&, 0&, _
        HWND_MESSAGE, 0&, _
        CLng(App.hInstance), 0&)
200    If myHwnd = 0 Then
201        lastError = apiGetLastError()
202        buffer = Space(200)
203        length = apiFormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM, ByVal API_NULL, lastError, LANG_NEUTRAL, buffer, 200, ByVal API_NULL)
204        If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": apiCreateWindowExA error (1): " & Left(buffer, length)
205        DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "1: " & Left(buffer, length)
206     End If
    
208    addMMFileTransport myHwnd, Me
    ' send a connection request
210    myIsWaitingForConnectionAcceptance = True
211    retval = apiPostMessageA(listeningHwnd, g_connectionRequestMessageID, myHwnd, 0)
212    If retval = 0 Then
213        lastError = apiGetLastError()
214        buffer = Space(200)
215        length = apiFormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM, ByVal API_NULL, lastError, LANG_NEUTRAL, buffer, 200, ByVal API_NULL)
216        If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": apiPostMessageA error (2): " & Left(buffer, length)
217        DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "2: " & Left(buffer, length)
218     End If

220    If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, "connectViaNamedWindow"
    
222 Exit Sub
223 exceptionHandler:
224     errorState = DBErrors_errorState()
225     myIsConnecting = False
226     DBTraceError ModuleSummary(), METHOD_NAME, errorState
228     DBErrors_reraiseErrorStateFrom errorState, ModuleSummary(), METHOD_NAME
End Sub


Sub disconnect()
233     Dim received As Boolean, retval As Long, buffer As String, length As Long, lastError As Long, callback As VLMMFileTransports
234     Const METHOD_NAME As String = "disconnect"
    
236     myIsDisconnecting = True
    
238     If myRemoteHwnd <> 0 And myHwnd <> 0 Then

        ' disconnectFromRemoteMMFile
241         unmapRemoteMMFile
242         If SHOW_TRACE Then DBTrace ModuleSummary, METHOD_NAME, myHwnd & ": unmap from MMFile " & MMFileName(myRemoteHwnd, myHwnd)
    
        ' attempt to delete mine
245         unmapMyMMFile
246         If SHOW_TRACE Then DBTrace ModuleSummary, METHOD_NAME, myHwnd & ": unmap MMFile " & MMFileName(myHwnd, myRemoteHwnd)
    
248     End If
    
250     If myRemoteHwnd <> 0 Then
251         retval = apiPostMessageA(myRemoteHwnd, g_connectionDisconnectMessageID, myHwnd, 0)
252         If retval = 0 Then
253             lastError = apiGetLastError()
254             buffer = Space(200)
255             length = apiFormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM, ByVal API_NULL, lastError, LANG_NEUTRAL, buffer, 200, ByVal API_NULL)
256             DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": apiPostMessageA error (1): " & Left(buffer, length)
257         End If
258         myRemoteHwnd = 0
259     End If
    
261     RaiseEvent disconnecting(received)
262     If myCallbackPtr <> 0 Then
263         VBoost.AssignAddRef callback, myCallbackPtr
264         callback.disconnecting myID, received
265     End If
    
267     If Not received Then
268         Call apiSetTimer(myHwnd, DISCONNECTING_TIMER_ID, TIMER_INTERVAL, API_NULL)
269         If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": event disconnecting not received starting DISCONNECTING_TIMER"
270     Else
271         finishDisconnection
272     End If
    
End Sub
    
Private Sub finishDisconnection()
277     Dim callback As VLMMFileTransports
278     If myHwnd <> 0 Then
279         removeMMFileTransport myHwnd
280         apiDestroyWindow myHwnd
281         myHwnd = 0
282     End If
283     myIsConnected = False
284     myIsConnecting = False
285     myIsWaitingForConnectionAcceptance = False
286     myIsDisconnecting = False
287     RaiseEvent disconnected
288     If myCallbackPtr <> 0 Then
289         VBoost.AssignAddRef callback, myCallbackPtr
290         callback.disconnected myID
291     End If
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' WndProc processing
'*************************************************************************************************************************************************************************************************************************************************

Friend Sub processWinProc(ByVal lMsg As Long, ByVal wparam As Long, ByVal lparam As Long)
300     Dim buffer1D() As Byte, length As Long, received As Boolean, retval As Long, buffer As String, lastError As Long, callback As VLMMFileTransports
301     Const METHOD_NAME As String = "processWinProc"

303     On Error GoTo exceptionHandler

305     If lMsg = WM_TIMER Then
306         If wparam = MESSAGE_ARRIVED_TIMER_ID Then
307             If myMessageInTransitQueue.count > 0 Then
308                 Do
309                     buffer1D = myMessageInTransitQueue(1)
310                     received = False
311                     RaiseEvent messageArrived(buffer1D, received)
312                     If myCallbackPtr <> 0 Then
313                         VBoost.AssignAddRef callback, myCallbackPtr
314                         callback.messageArrived myID, buffer1D, received
315                     End If
316                     If received Then myMessageInTransitQueue.remove 1
317                 Loop While myMessageInTransitQueue.count > 0 And received
318                 If received Then
319                     Call apiKillTimer(myHwnd, MESSAGE_ARRIVED_TIMER_ID)
320                     If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": killing MESSAGE_ARRIVED_TIMER"
321                 End If
322             Else
323                 Call apiKillTimer(myHwnd, MESSAGE_ARRIVED_TIMER_ID)
324                 If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": killing MESSAGE_ARRIVED_TIMER"
325             End If
326         End If
327         If wparam = CONNECTED_TIMER_ID Then
328             If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": CONNECTED_TIMER fired, ID=" & wparam
329             RaiseEvent connected(received)
330             If myCallbackPtr <> 0 Then
331                 VBoost.AssignAddRef callback, myCallbackPtr
332                 callback.connected myID, received
333             End If
334             If received Then
335                 Call apiKillTimer(myHwnd, CONNECTED_TIMER_ID)
336                 If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": killing CONNECTED_TIMER"
337             End If
338         End If
339         If wparam = DISCONNECTING_TIMER_ID Then
340             If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": DISCONNECTING_TIMER fired, ID=" & wparam
341             RaiseEvent disconnecting(received)
342             If myCallbackPtr <> 0 Then
343                 VBoost.AssignAddRef callback, myCallbackPtr
344                 callback.disconnecting myID, received
345             End If
346             If received Then
347                 Call apiKillTimer(myHwnd, DISCONNECTING_TIMER_ID)
348                 If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": killing DISCONNECTING_TIMER"
349                 finishDisconnection
350             End If
351         End If
352         Exit Sub
353     End If

355     If myIsDisconnecting Then Exit Sub
        
357     Select Case lMsg
    
        Case g_connectionAgreedMessageID
360             myRemoteHwnd = wparam
            
            ' connect to remote MMFile
363             myRemoteMMFileSize = lparam
364             connectToRemoteMMFile
365             If SHOW_TRACE Then DBTrace ModuleSummary, METHOD_NAME, myHwnd & ": connect(2) to MMFile " & MMFileName(myRemoteHwnd, myHwnd)
            
            ' create my MMFile
368             createMyMMFile
369             If SHOW_TRACE Then DBTrace ModuleSummary, METHOD_NAME, myHwnd & ": create(2) MMFile " & MMFileName(myHwnd, myRemoteHwnd)
            
371             myIsWaitingForConnectionAcceptance = False
372             myIsConnected = True
373             myIsConnecting = False
374             retval = apiPostMessageA(myRemoteHwnd, g_agreementAcknowledgedMessageID, myHwnd, myMMFileSize)
375             If retval = 0 Then
376                 lastError = apiGetLastError()
377                 buffer = Space(200)
378                 length = apiFormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM, ByVal API_NULL, lastError, LANG_NEUTRAL, buffer, 200, ByVal API_NULL)
379                 If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": apiPostMessageA error (1): " & Left(buffer, length)
380             End If
381             RaiseEvent connected(received)
382             If myCallbackPtr <> 0 Then
383                 VBoost.AssignAddRef callback, myCallbackPtr
384                 callback.connected myID, received
385             End If
386             If Not received Then
387                 Call apiSetTimer(myHwnd, CONNECTED_TIMER_ID, TIMER_INTERVAL, API_NULL)
388                 If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": connected not received (1) starting CONNECTED_TIMER_ID"
389             End If
390             If Not myIsSending And mySendQueue.count > 0 Then privateSendMessage
            
392             If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": g_connectionAgreedMessageID"
            
394         Case g_agreementAcknowledgedMessageID
            ' connect to remote MMFile
396             myRemoteMMFileSize = lparam
397             connectToRemoteMMFile
398             If SHOW_TRACE Then DBTrace ModuleSummary, METHOD_NAME, myHwnd & ": connect(3) to MMFile " & MMFileName(myRemoteHwnd, myHwnd)
399             myIsWaitingForConnectionAcceptance = False
400             myIsConnected = True
401             myIsConnecting = False
            
403             RaiseEvent connected(received)
404             If myCallbackPtr <> 0 Then
405                 VBoost.AssignAddRef callback, myCallbackPtr
406                 callback.connected myID, received
407             End If
408             If Not received Then
409                 Call apiSetTimer(myHwnd, CONNECTED_TIMER_ID, TIMER_INTERVAL, API_NULL)
410                 If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": connected not received (2) starting CONNECTED_TIMER_ID"
411             End If
412             If Not myIsSending And mySendQueue.count > 0 Then privateSendMessage

414             If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": g_agreementAcknowledgedMessageID"
            
416         Case g_connectionDisconnectMessageID
417             If SHOW_TRACE Then DBTrace ModuleSummary, METHOD_NAME, myHwnd & ": g_connectionDisconnectMessageID"
418             disconnect
419             If SHOW_TRACE Then DBTrace ModuleSummary, METHOD_NAME, myHwnd & ": g_connectionDisconnectMessageID post disconnect"
            
421         Case g_messageInTransitID
            ' read it from the MMFile
423             If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": g_messageInTransitID"
424             apiCopyMemory length, ByVal myRemoteMMFileBaseAddr, 4
425             If (length + MMFILE_HEADER_SIZE) > myRemoteMMFileSize Then
426                 retval = apiPostMessageA(myRemoteHwnd, g_messageGarbledMessageID, myHwnd, 0)
427                 If retval = 0 Then
428                     lastError = apiGetLastError()
429                     buffer = Space(200)
430                     length = apiFormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM, ByVal API_NULL, lastError, LANG_NEUTRAL, buffer, 200, ByVal API_NULL)
431                     If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": apiPostMessageA error (2): " & Left(buffer, length)
432                 End If
433             Else
434                 DBCreateNewArrayOfBytes buffer1D, 1, length
435                 apiCopyMemory buffer1D(1), ByVal myRemoteMMFileBaseAddr + 4, length
                ' let the sender know we got the message ok
437                 retval = apiPostMessageA(myRemoteHwnd, g_messageReceivedMessageID, myHwnd, 0)
438                 If retval = 0 Then
439                     lastError = apiGetLastError()
440                     buffer = Space(200)
441                     length = apiFormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM, ByVal API_NULL, lastError, LANG_NEUTRAL, buffer, 200, ByVal API_NULL)
442                     If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": apiPostMessageA error (3): " & Left(buffer, length)
443                 End If
444                 myMessageInTransitQueue.Add buffer1D
445                 Do
446                     buffer1D = myMessageInTransitQueue(1)
447                     received = False
448                     RaiseEvent messageArrived(buffer1D, received)   ' excel can block if it does queue the messages and kick off a timer
449                     If myCallbackPtr <> 0 Then
450                         VBoost.AssignAddRef callback, myCallbackPtr
451                         callback.messageArrived myID, buffer1D, received
452                     End If
453                     If received Then
                        ' although this looks like an impossible situation the callback could have issued DoEvents and a timer event got to the client before we did
455                         If myMessageInTransitQueue.count > 0 Then myMessageInTransitQueue.remove 1
456                     End If
457                 Loop While myMessageInTransitQueue.count > 0 And received
458                 If myMessageInTransitQueue.count > 0 Then
459                     Call apiSetTimer(myHwnd, MESSAGE_ARRIVED_TIMER_ID, TIMER_INTERVAL, API_NULL)        ' the timer will fire every 50mS in an attempt to deliver the queued messages
460                     If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": messageArrived() not received starting MESSAGE_ARRIVED_TIMER"
461                 End If
462             End If
            
464         Case g_messageReceivedMessageID
465             If myIsSending = True Then myIsSending = False
466             If mySendQueue.count > 0 Then privateSendMessage
467             If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": g_messageReceivedMessageID"
            
469         Case g_messageGarbledMessageID
470             If myIsSending = True Then myIsSending = False
471             If mySendQueue.count > 0 Then privateSendMessage
472             If SHOW_TRACE Then DBTrace ModuleSummary(), METHOD_NAME, myHwnd & ": g_messageGarbledMessageID"
            
474     End Select
475 Exit Sub
476 exceptionHandler:
477     DBTraceError ModuleSummary(), METHOD_NAME, DBErrors_errorState()
478     DBTrace ModuleSummary(), METHOD_NAME, "Erl: " & Erl()
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' MMFile mapping / unmapping
'*************************************************************************************************************************************************************************************************************************************************

Private Sub createMyMMFile()
487     Const METHOD_NAME As String = "createMyMMFile"
488     If myMMFileHandle > 0 Then DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "myMMFileHandle > 0"
489     myMMFileHandle = apiCreateFileMappingA(INVALID_HANDLE_VALUE, ByVal 0&, PAGE_READWRITE, 0&, myMMFileSize, MMFileName(myHwnd, myRemoteHwnd))
490     If myMMFileHandle = 0 Then DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "myMMFileHandle = 0"
491     myMMFileBaseAddr = apiMapViewOfFile(myMMFileHandle, FILE_MAP_ALL_ACCESS, 0&, 0&, 0&)
492     If myMMFileBaseAddr = 0 Then DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "myMMFileBaseAddr = 0"
End Sub

Private Sub connectToRemoteMMFile()
496     Const METHOD_NAME As String = "connectToRemoteMMFile"
497     myRemoteMMFileHandle = apiOpenFileMappingA(FILE_MAP_ALL_ACCESS, 0&, MMFileName(myRemoteHwnd, myHwnd))
498     If myRemoteMMFileHandle = 0 Then DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "myRemoteMMFileHandle = 0"
499     myRemoteMMFileBaseAddr = apiMapViewOfFile(myRemoteMMFileHandle, FILE_MAP_ALL_ACCESS, 0&, 0&, 0&)
500     If myRemoteMMFileBaseAddr = 0 Then DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "myRemoteMMFileBaseAddr = 0"
End Sub

Private Sub unmapMyMMFile()
504     Const METHOD_NAME As String = "unmapMyMMFile"
505     If apiUnmapViewOfFile(myMMFileBaseAddr) = 0 Then DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "apiUnmapViewOfFile(myMMFileBaseAddr) = 0"
506     If apiCloseHandle(myMMFileHandle).BOOL = BOOL_FALSE Then DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "apiCloseHandle(myMMFileHandle).BOOL"
507     myMMFileBaseAddr = 0
508     myMMFileHandle = 0
End Sub

Private Sub unmapRemoteMMFile()
512     Const METHOD_NAME As String = "unmapRemoteMMFile"
513     If apiUnmapViewOfFile(myRemoteMMFileBaseAddr) = 0 Then DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "apiUnmapViewOfFile(myRemoteMMFileBaseAddr) = 0"
514     If apiCloseHandle(myRemoteMMFileHandle).BOOL = BOOL_FALSE Then DBErrors_raiseGeneralError ModuleSummary(), METHOD_NAME, "apiCloseHandle(myRemoteMMFileHandle).BOOL = BOOL_FALSE"
515     myRemoteMMFileBaseAddr = 0
516     myRemoteMMFileHandle = 0
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' Initialize / Release
'*************************************************************************************************************************************************************************************************************************************************

Private Sub Class_Initialize()
525     ensureWindowsMessagesExist
End Sub

Private Sub Class_Terminate()
529     If (myIsConnected Or myIsConnecting) And Not myIsDisconnecting Then disconnect
530     If (myIsConnected Or myIsConnecting) And myIsDisconnecting Then finishDisconnection
End Sub


'*************************************************************************************************************************************************************************************************************************************************
' module summary
'*************************************************************************************************************************************************************************************************************************************************

Private Function ModuleSummary() As Variant()
    ModuleSummary = Array(1, GLOBAL_PROJECT_NAME, MODULE_NAME, MODULE_VERSION)
End Function

