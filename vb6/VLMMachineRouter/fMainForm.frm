VERSION 5.00
Begin VB.Form fMainForm 
   Caption         =   "(Design) ID Directory"
   ClientHeight    =   3195
   ClientLeft      =   60
   ClientTop       =   345
   ClientWidth     =   4680
   Icon            =   "fMainForm.frx":0000
   KeyPreview      =   -1  'True
   LinkTopic       =   "Form1"
   MaxButton       =   0   'False
   MinButton       =   0   'False
   ScaleHeight     =   213
   ScaleMode       =   3  'Pixel
   ScaleWidth      =   312
   ShowInTaskbar   =   0   'False
   StartUpPosition =   3  'Windows Default
   WindowState     =   1  'Minimized
End
Attribute VB_Name = "fMainForm"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Option Explicit

Private Declare Function SetWindowText Lib "user32.dll" Alias "SetWindowTextA" (ByVal hwnd As Long, ByVal lpString As String) As Long
Private myApplication As cApplication

' Event order on a key press is KeyDown, KeyPress, KeyUp
Private Sub Form_KeyDown(KeyCode As Integer, Shift As Integer)
    If KeyCode = 27 Then Me.Hide
End Sub

Private Sub Form_KeyPress(KeyAscii As Integer)
'
End Sub

Private Sub Form_KeyUp(KeyCode As Integer, Shift As Integer)
'
End Sub


Private Sub Form_Resize()
    Select Case Me.WindowState
        Case vbNormal
        Case vbMinimized
        Case vbMaximized
    End Select
'    MsgBox "Resize state: " & Me.WindowState
'    Me.ScaleHeight = 213
'    Me.ScaleWidth = 312
End Sub

Private Sub Form_Initialize()
    Me.WindowState = vbMinimized
    Me.ScaleMode = vbPixels
    If machineRouterHWnd() = 0 Then Set myApplication = New cApplication       ' there are problems with App.PrevInstance so use an explicit search
End Sub

Private Sub Form_Load()
    SetWindowText Me.hwnd, vbNullString
End Sub

Private Sub Form_QueryUnload(Cancel As Integer, UnloadMode As Integer)
    If UnloadMode = vbFormControlMenu Then
        Me.Hide
        Cancel = True
    End If
End Sub

Private Sub Form_Terminate()
'
End Sub

Private Sub Form_Unload(Cancel As Integer)
'
End Sub
