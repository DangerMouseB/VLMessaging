VERSION 5.00
Begin VB.Form fMouseEventsForm 
   Caption         =   "Form1"
   ClientHeight    =   3195
   ClientLeft      =   60
   ClientTop       =   345
   ClientWidth     =   4680
   Icon            =   "fMouseEvents.frx":0000
   LinkTopic       =   "Form1"
   ScaleHeight     =   3195
   ScaleWidth      =   4680
   ShowInTaskbar   =   0   'False
   StartUpPosition =   3  'Windows Default
   Visible         =   0   'False
   Begin VB.Timer PingTimer 
      Interval        =   500
      Left            =   120
      Top             =   120
   End
End
Attribute VB_Name = "fMouseEventsForm"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
'*************************************************************************************************************************************************************************************************************************************************
'
' Copyright (c) David Briant 2009-2012 - All rights reserved
'
'*************************************************************************************************************************************************************************************************************************************************

Option Explicit

Event PingTimer()

Private Sub PingTimer_Timer()
    RaiseEvent PingTimer
End Sub
