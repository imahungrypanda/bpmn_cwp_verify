
//pt_COVID_19
inline pt_COVID_19_BehaviorModel(){
    skip
}
//T01
inline T01_BehaviorModel(){
    assert(sevNeed != discharge)
    assert(sevNeed != expired)
    if
    :: true -> sevNeed = homeCare
    :: ((sevNeed == INIT) || (trndSevNeed == outsideHomeCare)) -> sevNeed = outsideHomeCare
    :: ((sevNeed != INIT) && (trndSevNeed == homeCare)) -> sevNeed = discharge
    fi
    trndSevNeed = sevNeed
    updateState()
}
//Xor5_sevLvl
inline Xor5_sevLvl_BehaviorModel(){
    skip
}
//T02
inline T02_BehaviorModel(){
    updateState()
}
//pt_discharged
inline pt_discharged_BehaviorModel(){
    skip
}
//Event_0hqgm9w
inline Event_0hqgm9w_BehaviorModel(){
    skip
}
//Xor8_alert
inline Xor8_alert_BehaviorModel(){
    skip
}
//Event_19rhey4
inline Event_19rhey4_BehaviorModel(){
    skip
}
//T07
inline T07_BehaviorModel(){
    alert = no
    if
    :: examTime == scheduled -> examTime = now
    :: true
    fi
    updateState()
}
//Xor10_exam_orders
inline Xor10_exam_orders_BehaviorModel(){
    skip
}
//T08b
inline T08b_BehaviorModel(){
    if
        :: true -> examTime = scheduled
    fi
    updateState()
}
//Xor11_examTimenow
inline Xor11_examTimenow_BehaviorModel(){
    skip
}
//T07a
inline T07a_BehaviorModel(){
    alert = no
    if
    :: examTime == scheduled -> examTime = now
    :: true
    fi
    updateState()
}
//Xor9_exam_orders
inline Xor9_exam_orders_BehaviorModel(){
    skip
}
//pt_discharged1
inline pt_discharged1_BehaviorModel(){
    skip
}
//pt_expired
inline pt_expired_BehaviorModel(){
    skip
}
//T03
inline T03_BehaviorModel(){
    assert(sevNeed != discharge)
    assert(sevNeed != expired)
    if
    :: true -> sevNeed = expired
    :: true -> sevNeed = discharge
    fi
    trndSevNeed = sevNeed
    updateState()
}
//Xor4_fatality
inline Xor4_fatality_BehaviorModel(){
    skip
}
//Event_1bg3bap
inline Event_1bg3bap_BehaviorModel(){
    skip
}
//T08a
inline T08a_BehaviorModel(){
    if
        :: true -> examTime = now
    fi
    updateState()
}
//Event_1v0tpdm
inline Event_1v0tpdm_BehaviorModel(){
    skip
}
//End232
inline End232_BehaviorModel(){
    skip
}
//T06
inline T06_BehaviorModel(){
    if
    :: sevNeed == discharge
    :: else ->
        if
        :: true -> trndSevNeed = homeCare
        :: true -> trndSevNeed = outsideHomeCare
            if
            :: true -> alert = yes
            :: true -> alert = no
            fi
        fi
    fi
    updateState()
}
//Start170
inline Start170_BehaviorModel(){
    skip
}
//T04
inline T04_BehaviorModel(){
    updateState()
}
//T05
inline T05_BehaviorModel(){
    if
    :: trndSevNeed == outsideHomeCare ->
        sevNeed = expired
    :: true
    fi
    updateState()
}
//Xor6_fatality
inline Xor6_fatality_BehaviorModel(){
    skip
}
//pt_expired1
inline pt_expired1_BehaviorModel(){
    skip
}
//Xor7_examTime_now
inline Xor7_examTime_now_BehaviorModel(){
    skip
}
//EHR
inline EHR_BehaviorModel(){
    skip
}
//End196
inline End196_BehaviorModel(){
    skip
}
//seconds_throw_pt
inline seconds_throw_pt_BehaviorModel(){
    skip
}
