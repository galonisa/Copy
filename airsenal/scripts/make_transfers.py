"""
Script to apply recommended transfers from the current transfer suggestion table.

Ref:
https://github.com/sk82jack/PSFPL/blob/master/PSFPL/Public/Invoke-FplTransfer.ps1
https://www.reddit.com/r/FantasyPL/comments/b4d6gv/fantasy_api_for_transfers/
https://fpl.readthedocs.io/en/latest/_modules/fpl/models/user.html#User.transfer
"""
import argparse
from prettytable import PrettyTable
import requests, json, getpass

from airsenal.framework.schema import TransferSuggestion
from airsenal.framework.optimization_utils import get_starting_squad
from airsenal.framework.utils import session, get_player_name, get_sell_price_for_player, get_bank, get_player
from airsenal.scripts.get_transfer_suggestions import get_transfer_suggestions, build_strategy_string

from airsenal.framework.data_fetcher import FPLDataFetcher

import click

"""
TODO:
- confirm points loss
- implement token use
- Check for edge-cases
- write a test. 
"""

@click.command("airsenal_make_transfers")

@click.option(
    "--fpl_team_id",
    type=int,
    required=False,
    help="fpl team id to make suggested transfers for",
)

def check_proceed():
    proceed = input("Apply Transfers? There is no turning back! (yes/no)")
    if proceed == "yes":
        print("Applying Transfers...")
        return True
    else: 
        return False

def deduct_transfer_price(pre_bank, priced_transfers):

    gain = [transfer[0][1] - transfer[1][1] for transfer in priced_transfers]
    return(pre_bank + sum(gain))


def print_output(team_id, current_gw, priced_transfers, pre_bank, post_bank, points_cost='TODO'):

    print("\n")
    header = f"Transfers to apply for fpl_team_id: {team_id} for gameweek: {current_gw}"
    line = "=" * len(header)
    print(f"{header} \n {line} \n")

    print(f"Bank Balance Before transfers is: £{pre_bank/10}")

    t = PrettyTable(['Status','Name','Price'])
    for transfer in priced_transfers:
        t.add_row(['OUT',get_player_name(transfer[0][0]),f"£{transfer[0][1]/10}"])
        t.add_row(['IN',get_player_name(transfer[1][0]),f"£{transfer[1][1]/10}"])

    print(t)

    print(f"Bank Balance After transfers is: £{post_bank/10}")
    print(f"Points Cost of Transfers: {points_cost}")
    print("\n")

def get_sell_price(team_id, player_id):

    squad = get_starting_squad(team_id)
    for p in squad.players: 
        if p.player_id == player_id:
            return(squad.get_sell_price_for_player(p))

def price_transfers(transfer_player_ids, fetcher, current_gw):

    transfers = (list(zip(*transfer_player_ids))) #[(out,in),(out,in)]
    
    #[[[out, price], [in, price]],[[out,price],[in,price]]]
    priced_transfers = [[[t[0],get_sell_price(fetcher.FPL_TEAM_ID, t[0])],
                        [t[1], fetcher.get_player_summary_data()[get_player(t[1]).fpl_api_id]["now_cost"]]]
                        for t in transfers]

    return(priced_transfers)


def get_gw_transfer_suggestions(fpl_team_id=None):
    
    ## gets the transfer suggestions for the latest optimization run, regardless of fpl_team_id
    rows = get_transfer_suggestions(session, TransferSuggestion)
    if fpl_team_id and fpl_team_id != rows[0].fpl_team_id: 
        raise Exception(f'Team ID passed is {fpl_team_id}, but transfer suggestions are for team ID {rows[0].fpl_team_id}. We recommend re-running optimization.') 
    else:
        fpl_team_id = rows[0].fpl_team_id
    current_gw = rows[0].gameweek
    players_out, players_in = [],[]

    for row in rows:
        if row.gameweek == current_gw:
            if row.in_or_out < 0: 
                players_out.append(row.player_id)
            else:
                players_in.append(row.player_id) 
    return([players_out, players_in], fpl_team_id, current_gw)
    
def build_transfer_payload(priced_transfers, current_gw, fetcher):

    to_dict = lambda t: {
                        "element_out": get_player(t[0][0]).fpl_api_id,
                        "selling_price": t[0][1],
                        "element_in": get_player(t[1][0]).fpl_api_id,
                        "purchase_price": t[1][1]
    }

    transfer_list = [to_dict(transfer) for transfer in priced_transfers]

    transfer_payload = { 
	    "confirmed": False,
	    "entry": fetcher.FPL_TEAM_ID, #not sure what the entry should refer to?
	    "event": current_gw,
	    "transfers": transfer_list,
	    "wildcard": False,
	    "freehit": False
    }

    print(transfer_payload)

    return(transfer_payload) 

def login(session, fetcher):

    if (not fetcher.FPL_LOGIN) or (not fetcher.FPL_PASSWORD) or (fetcher.FPL_LOGIN == "MISSING_ID") or (fetcher.FPL_PASSWORD == "MISSING_ID"):
        fetcher.FPL_LOGIN = input("Please enter FPL login: ")
        fetcher.FPL_PASSWORD = getpass.getpass("Please enter FPL password: ")
    
    
    #print("FPL credentials {} {}".format(fetcher.FPL_LOGIN, fetcher.FPL_PASSWORD))
    login_url = "https://users.premierleague.com/accounts/login/"
    headers = {
        "login": fetcher.FPL_LOGIN,
        "password": fetcher.FPL_PASSWORD,
        "app": "plfpl-web",
        "redirect_uri": "https://fantasy.premierleague.com/a/login",
    }
    session.post(login_url, data=headers)
    return session

def post_transfers(transfer_payload, fetcher):

    session = requests.session()

    session = login(session, fetcher)
    
    #code below adapted from from https://github.com/amosbastian/fpl/blob/master/fpl/utils.py
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://fantasy.premierleague.com/a/squad/transfers"
    }

    transfer_url= "https://fantasy.premierleague.com/api/transfers/"
    

    resp = session.post(transfer_url, data=json.dumps(transfer_payload), headers=headers)
    if "non_form_errors" in resp:
            raise Exception(post_response["non_form_errors"])
    elif resp.status_code == 200:
        print("SUCCESS....transfers made!")
    else:
        print("Transfers unsuccessful due to unknown error")
        print(f"Response status code: {resp.status_code}")
        print(f"Response text: {resp.text}")


def main(fpl_team_id = None):

    transfer_player_ids, team_id, current_gw = get_gw_transfer_suggestions(fpl_team_id)

    fetcher = FPLDataFetcher(team_id)

    pre_transfer_bank = get_bank(fpl_team_id=team_id)
    priced_transfers = price_transfers(transfer_player_ids, fetcher, current_gw)
    post_transfer_bank = deduct_transfer_price(pre_transfer_bank, priced_transfers)

    print_output(team_id,current_gw, priced_transfers, pre_transfer_bank, post_transfer_bank)
    

    if check_proceed():
        transfer_req = build_transfer_payload(priced_transfers, current_gw, fetcher)
        post_transfers(transfer_req, fetcher)
    

if __name__ == "__main__":
    
    main()
        