import React, { useState, useEffect, useContext } from "react";

import {
    NavLink,
    HashRouter,
  } from "react-router-dom";

import { ServerIp, GitRepo }  from "./common"
import { AuthContext } from "./App";



function AllRuns () {
    const { state } = useContext(AuthContext);

    const [allRuns, setAllRuns] = useState([]);
    
    const [member, setMember] = useState([]);
    
    const [filteredRuns, setFilteredRuns] = useState([])
    
    const { organizations_url } = state.user
    fetch(organizations_url, {  
    })
    .then(response => response.json())
    .then(data => {
     for (var d of data) {
        if (d["login"] === "nearprotocol") {
            console.log("Welcome to Nay!");
            setMember(true);
        }
     }
    });
  
    
    useEffect(() => {
            fetch(ServerIp(), {
              headers : { 
                'Content-Type': 'application/json',
                'Accept': 'application/json'
               }
              }).then((response) => response.json())
              .then(data => {
              setAllRuns(data);
              setFilteredRuns(data)
            })
            
            .catch(function(err) {
              console.log('Fetch Error :-S', err);
            });
    }, []);

    var filterClick = event  => {
      var filters = document.getElementsByName("filters");
      for (var item of filters) {
        item.value = "";
      }
      setFilteredRuns(allRuns);
    }

    var filterHandler = event => {
      const fltr = event.target.value.toLowerCase();
      var id = event.target.id;
      setFilteredRuns(
        allRuns.filter(
          item =>
            (String(item[id]).toLowerCase().includes(fltr)) 
        )
      );
    };

    var cancelRun = id => event => {
      fetch(ServerIp() + '/cancel_the_run', {
        headers : { 
          'Content-Type': 'application/json',
          'Accept': 'application/json'
         },
         method: 'POST',
         body: JSON.stringify({'run_id': id}),
        }).then((response) => response.json())
        .then(data => {
          console.log(data);
      })
    }

    return (
        <div className="App">
        <HashRouter>
          <table className="big"><tbody>
          <tr>
            <th>Branch
            <input style={{"width":"100%"}} type="text" name="filters" id="branch" onChange={filterHandler} onClick={filterClick}/>
            </th>
            <th style={{"width": "30%"}}>Title
            <input style={{"width":"100%"}} type="text" name="filters" id="title" onChange={filterHandler} onClick={filterClick}/>
            </th>
            <th>User
            <input style={{"width":"100%"}} type="text" name="filters" id="requester" onChange={filterHandler} onClick={filterClick}/>
            </th>
            <th>Run Type
            <input style={{"width":"100%"}} type="text" name="filters" id="type" onChange={filterHandler} onClick={filterClick}/>
            </th>
            
            <th width="40%">Status</th>
            { member > 0 ? <th>x</th>:''}
              
          </tr>
          {filteredRuns.map((a_run,i) =>
            <tr key={a_run.id}>
              <td><p style={{"font-size": "x-small", "margin":"0"}}>{a_run.branch}</p>
                <a href={GitRepo()+"/commit/"+a_run.sha.slice(0,7)}>
                    {a_run.sha.slice(0,7)}
                </a>
              </td>
              <td>
                <NavLink to={"/run/" + a_run.id} name="title">{a_run.title}</NavLink>
              </td>
              <td style={{"font-size": "x-small"}}>{a_run.requester}</td>
              <td style={{"font-size": "x-small"}}>{a_run.type}</td>
              <td >
          
              { a_run.passed > 0 ? <div class="status" style={{"background": "green", }}>{a_run.passed} passed</div> : ''}
              { a_run.failed > 0 ? <div class="status" style={{"background": "red" , }}>{a_run.failed} failed </div> : ''}
              { a_run.timeout > 0 ? <div class="status" style={{"background": "#f0a3aa", }}>{a_run.timeout} timeout </div> : ''}
              { a_run.build_failed > 0 ? <div class="status" style={{"background": "#864E4E", }}>{a_run.build_failed} build failed </div> : ''}
              { a_run.canceled > 0 ? <div class="status" style={{"background": "#FCF88C",}}> {a_run.canceled} canceled </div> : ''}
              { a_run.ignored > 0 ? <div class="status" style={{"background": "grey", }}>{a_run.ignored} ignored</div> : ''}
              { a_run.pending > 0 ? <div class="status" style={{"background": "#ED8CFC"}}> {a_run.pending} pending </div> : ''}
              { a_run.running > 0 ? <div class="status" style={{"background": "#697DCB", }}>{a_run.running} running</div> : ''}
              </td> 
              { member > 0 ? <td><button style={{"border-radius": "4px", "cursor": "pointer"}}onClick={cancelRun(a_run.id)}>x</button></td> : ''}
            </tr>)
          }
          </tbody></table>
        </HashRouter>
        </div>
        );
}
  
export default AllRuns;
